"""命令处理器 — 对接 protocol_tool API。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from console.command import registry, Command, Param

ROOT = Path(__file__).resolve().parent.parent  # wireforge/


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class CmdResult:
    """命令执行结果。"""
    success: bool
    command: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    path: str = ""          # 路由调用链
    frame_hex: str = ""     # 构造/解析的报文

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"success": self.success, "command": self.command}
        if self.output: d["output"] = self.output
        if self.error:  d["error"] = self.error
        if self.path:   d["path"] = self.path
        if self.frame_hex: d["frame"] = self.frame_hex
        return d


# ── Helpers ───────────────────────────────────────────────────────────

def _proto(name: str) -> str:
    m = {"dlt645": "dlt645_2007", "dlt645_2007": "dlt645_2007",
         "csg": "csg_2016", "csg_2016": "csg_2016"}
    return m.get(name, name)


def _ensure_ir(proto: str):
    ip = ROOT / "compiled" / f"{proto}.ir.json"
    if not ip.exists():
        from protocol_tool.compiler.pipeline import compile_protocol
        reg = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
        compile_protocol(str(reg), proto, output_dir=str(ROOT / "compiled"))


def _hex(v: Any) -> int:
    """将 hex 字符串或 int 转为 int。"""
    if isinstance(v, int): return v
    s = str(v).replace("0x", "").replace("0X", "")
    return int(s, 16)


# ── Build ─────────────────────────────────────────────────────────────

def handle_build(args: dict[str, Any]) -> CmdResult:
    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto}.ir.json"))

    if proto == "dlt645_2007":
        func = _hex(args.get("func", 0x11))
        dn = args.get("dir", "downlink")
        dv = 0 if dn == "downlink" else 1
        info = {"func": func, "direction": dn}
        fv = {"preamble": 4, "address": "000000000001",
              "control": {"func": func, "dir": dv, "ack": 0, "follow": 0},
              "di": args.get("di", "00010000")}
        if func == 0x13:
            if dv == 0: fv["address"] = "AAAAAAAAAAAA"
            else: fv["address_data"] = "000000000001"
    else:
        afn = _hex(args.get("afn", 0))
        di_val = args.get("di", f"E800{afn:02X}01")
        dn = args.get("dir", "downlink")
        ha = args.get("addr", False)
        info = {"afn": afn, "di": di_val, "direction": dn, "has_address": bool(ha)}
        fv = {"afn": afn, "seq": 1, "di": di_val}
        if ha:
            fv["address_area"] = {"asrc": "000000000001", "adst": "000000000000"}

    be = BuildEngine(ir, create_builtin_registry())
    de = DecodeEngine(ir, create_builtin_registry())
    try:
        path_info = be.resolve_path(info)
        r = be.build(fv, info=info)
        de.decode(r.frame)
        return CmdResult(
            success=True, command="build",
            path=r.path_str, frame_hex=r.frame_hex,
            output={"protocol": proto, "path": r.path_str},
        )
    except ValueError as e:
        # 路径不存在: 尝试 resolve 获取部分路径
        partial_path = ""
        try: partial_path = " → ".join(
            s["leaf_name"] for s in be.resolve_path({k: v for k, v in info.items() if k != "has_address"}).get("path", [])
        ) if "resolve_path" in dir(be) else ""
        except Exception: pass
        return CmdResult(
            success=False, command="build", error=str(e),
            path=partial_path,
        )
    except Exception as e:
        return CmdResult(success=False, command="build", error=str(e))


# ── Decode ────────────────────────────────────────────────────────────

def handle_decode(args: dict[str, Any]) -> CmdResult:
    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    hx = str(args.get("hex", "")).replace(" ", "").replace("\n", "")
    if not hx:
        return CmdResult(success=False, command="decode", error="hex: required")

    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto}.ir.json"))
    de = DecodeEngine(ir, create_builtin_registry())
    try:
        frame = bytes.fromhex(hx)
        result = de.decode(frame)
        values = {}
        for k, v in result.values.items():
            if isinstance(v, dict):
                values[k] = v
            elif not k.startswith(("csg_", "read_")):
                values[k] = v
        return CmdResult(
            success=True, command="decode",
            path=result.path_str, frame_hex=result.raw_hex,
            output={"protocol": proto, "values": values, "warnings": result.warnings},
        )
    except Exception as e:
        return CmdResult(success=False, command="decode", error=str(e))


# ── 注册 ──────────────────────────────────────────────────────────────

registry.register(Command(
    name="build",
    desc="构造协议报文",
    params=[
        Param("proto", "choice", required=True, desc="协议", values=["dlt645", "csg"]),
        Param("func", "hex", desc="功能码 (DLT645)"),
        Param("afn", "hex", desc="AFN (CSG)"),
        Param("di", "str", desc="DI 数据标识"),
        Param("dir", "choice", desc="方向", values=["downlink", "uplink"]),
        Param("addr", "bool", desc="带地址域 (CSG)"),
    ],
    timeout=15000,
), handle_build)

registry.register(Command(
    name="decode",
    desc="解析协议报文",
    params=[
        Param("proto", "choice", required=True, desc="协议", values=["dlt645", "csg"]),
        Param("hex", "str", required=True, desc="十六进制报文字节流"),
    ],
    timeout=15000,
), handle_decode)
