"""协议 build/decode 共享工具（check.py 与 CSG 全量配对测试复用）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tests.csg_pair_catalog import PairMessage, to_route_info as csg_to_route_info, _afn_to_int
from tests.dlt645_pair_catalog import Dlt645PairMessage, to_route_info as dlt645_to_route_info


def auto_fill_leaf_fields(leaf, defaults, base_fv=None, ir=None):
    """根据 leaf 的字段定义自动填充默认值。若字段是 routed_payload，递归填充子 leaf。"""
    fv = dict(base_fv or {})
    for lf in leaf.fields:
        if lf.optional or lf.name in fv:
            continue
        t = lf.type_ref
        n = lf.name
        if n in defaults and not (t == "struct" and isinstance(defaults.get(n), str)):
            fv[n] = defaults[n]
            if t == "bcd_numeric" and isinstance(fv[n], dict) and "raw" in fv[n]:
                want = (lf.length or 4) * 2
                raw = fv[n]["raw"]
                if len(raw) > want:
                    fv[n] = {"raw": raw[:want]}
                elif len(raw) < want:
                    fv[n] = {"raw": raw.ljust(want, "0")}
        elif t == "struct" and n + "_struct" in defaults:
            fv[n] = defaults[n + "_struct"]
        elif n in defaults:
            fv[n] = defaults[n]
        elif t == "uint8":
            fv[n] = 0x01
        elif t == "enum":
            fv[n] = 0x00
        elif t == "bcd":
            fv[n] = "01" * (lf.length or 1)
        elif t == "hex":
            fv[n] = "00" * (lf.length or 2)
        elif t == "bytes":
            fv[n] = bytes([0x01] * (lf.length or 2))
        elif t == "ascii":
            fv[n] = "A" * (lf.length or 2)
        elif t == "bitset":
            fv[n] = {}
        elif t == "struct":
            sub = {}
            for sf in lf.params.get("fields", []):
                sn = sf.get("name", "")
                st = sf.get("type", "uint8")
                if sn in defaults:
                    sub[sn] = defaults[sn]
                elif st == "hex":
                    sub[sn] = "00"
                elif st == "bcd":
                    sub[sn] = "01" * (sf.get("length", 1))
                elif st in ("uint8", "enum"):
                    sub[sn] = 0x00
            fv[n] = sub
        elif t == "bcd_numeric":
            nbytes = lf.length or 2
            fv[n] = {"raw": "00" * (nbytes * 2)}
        elif t == "array":
            item_type = lf.params.get("item_type", "hex")
            count = lf.length or lf.params.get("count")
            if n in defaults:
                val = defaults[n]
                if isinstance(val, str) and item_type == "ascii" and count:
                    fv[n] = list(val[:count].ljust(count, "A"))
                else:
                    fv[n] = val
            elif item_type == "ascii" and count:
                fv[n] = ["A"] * count
            elif item_type in ("uint8", "enum") and count:
                fv[n] = [0x01] * count
            elif count:
                fv[n] = ["01"] * count
        elif t == "routed_payload" and ir:
            sub_router = lf.params.get("router", "")
            if sub_router in ir.routers:
                rnode = ir.routers[sub_router]
                keys = []
                for path in rnode.key_paths:
                    short = path.split(".", 1)[-1]
                    val = fv.get(short, defaults.get(short, 0))
                    keys.append(val)
                key_str = json.dumps(keys, separators=(",", ":")) if len(keys) > 1 else (
                    keys[0] if isinstance(keys[0], str) else json.dumps(keys)
                )
                lid = rnode.route_table.get(key_str)
                if lid and lid in ir.leaves:
                    sub_leaf = ir.leaves[lid]
                    sub_fv = auto_fill_leaf_fields(sub_leaf, defaults, ir=ir)
                    for k, v in sub_fv.items():
                        if k not in fv:
                            fv[k] = v
    return fv


def build_csg_field_values(
    msg: PairMessage,
    leaf,
    defaults: dict[str, Any],
    ir,
    *,
    addr: str = "000000000001",
) -> dict[str, Any]:
    """为 CSG 单条消息构造 build 字段值。"""
    merged = dict(defaults)
    merged.update(msg.field_defaults)

    fv: dict[str, Any] = {
        "afn": _afn_to_int(msg.afn),
        "seq": 1,
        "di": msg.di,
    }
    if msg.has_address:
        fv["address_area"] = {
            "asrc": merged.get("address_area.asrc", addr),
            "adst": merged.get("address_area.adst", "000000000000"),
        }
    for key, val in merged.items():
        if key.startswith("address_area."):
            continue
        fv[key] = val
    return auto_fill_leaf_fields(leaf, merged, fv, ir)


@dataclass
class MessageTestResult:
    pair_id: str
    scenario_id: str
    slot: str
    side: str
    role: str | None
    afn: str
    di: str
    dir: str
    status: str  # PASS | FAIL | SKIP
    func: str = ""
    path_str: str = ""
    frame_hex: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {
            "pair_id": self.pair_id,
            "slot": self.slot,
            "scenario_id": getattr(self, "scenario_id", ""),
            "side": self.side,
            "role": self.role,
            "dir": self.dir,
            "status": self.status,
            "path_str": self.path_str,
            "frame_hex": self.frame_hex,
            "error": self.error,
        }
        if self.func:
            out["func"] = self.func
        if self.di:
            out["di"] = self.di
        if self.afn:
            out["afn"] = self.afn
        return out


def run_pair_message(
    msg: PairMessage,
    ir,
    build_engine,
    decode_engine,
    defaults: dict[str, Any],
    *,
    addr: str = "000000000001",
) -> MessageTestResult:
    """对单条配对消息执行 resolve_path → build → decode。"""
    info = csg_to_route_info(msg)
    base = MessageTestResult(
        pair_id=msg.pair_id,
        scenario_id=msg.scenario_id,
        slot=msg.slot,
        side=msg.side,
        role=msg.role,
        afn=msg.afn,
        di=msg.di,
        dir=msg.dir,
        status="FAIL",
    )
    try:
        path = build_engine.resolve_path(info)
    except ValueError as exc:
        base.error = f"path: {exc}"
        return base

    leaf = ir.leaves.get(path["leaf_id"])
    if leaf is None:
        base.error = f"leaf not found: {path['leaf_id']}"
        return base

    fv = build_csg_field_values(msg, leaf, defaults, ir, addr=addr)
    try:
        result = build_engine.build(fv, info=info)
        decode_engine.decode(result.frame)
    except Exception as exc:
        base.error = str(exc)
        return base

    base.status = "PASS"
    base.path_str = result.path_str
    base.frame_hex = result.frame_hex
    return base


def _preamble_default(ir) -> int:
    for ff in ir.frame.fields:
        if ff.name == "preamble":
            return ff.params.get("default", ff.params.get("min", 0))
    return 0


def build_dlt645_field_values(
    msg: Dlt645PairMessage,
    leaf,
    defaults: dict[str, Any],
    ir,
    *,
    addr: str = "000000000001",
) -> dict[str, Any]:
    """为 DLT645 单条消息构造 build 字段值。"""
    merged = dict(defaults)
    merged.update(msg.field_defaults)

    func = int(msg.func, 16)
    dir_val = 0 if msg.dir == "downlink" else 1
    fv: dict[str, Any] = {
        "preamble": _preamble_default(ir),
        "address": addr,
        "control": {"func": func, "dir": dir_val, "ack": 0, "follow": 0},
    }
    fv.update(msg.frame_defaults)
    for key, val in merged.items():
        fv[key] = val
    return auto_fill_leaf_fields(leaf, merged, fv, ir)


def run_dlt645_pair_message(
    msg: Dlt645PairMessage,
    ir,
    build_engine,
    decode_engine,
    defaults: dict[str, Any],
    *,
    addr: str = "000000000001",
) -> MessageTestResult:
    """对单条 DLT645 配对消息执行 resolve_path → build → decode。"""
    info = dlt645_to_route_info(msg)
    base = MessageTestResult(
        pair_id=msg.pair_id,
        scenario_id=getattr(msg, "scenario_id", "default"),
        slot=msg.slot,
        side=msg.side,
        role=msg.role,
        func=msg.func,
        di=msg.di or "",
        afn="",
        dir=msg.dir,
        status="FAIL",
    )
    try:
        path = build_engine.resolve_path(info)
    except ValueError as exc:
        base.error = f"path: {exc}"
        return base

    leaf = ir.leaves.get(path["leaf_id"])
    if leaf is None:
        base.error = f"leaf not found: {path['leaf_id']}"
        return base

    fv = build_dlt645_field_values(msg, leaf, defaults, ir, addr=addr)
    try:
        result = build_engine.build(fv, info=info)
        decode_engine.decode(result.frame)
    except Exception as exc:
        base.error = str(exc)
        return base

    base.status = "PASS"
    base.path_str = result.path_str
    base.frame_hex = result.frame_hex
    return base
