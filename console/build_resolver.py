"""两阶段 Build: Resolve → Encode。

Phase 1: resolve(target_info) → BuildTarget
  输入目标定位信息 → 路由查找 → 生成 input_schema

Phase 2: encode(target, user_values) → bytes
  用 input_schema 校验用户输入 → 构造完整帧

字段分类:
  A. 目标定位: protocol, di, func, afn, intent, dir
  B. 链路/帧上下文: address, preamble
  C. 业务数据:   由 variant schema 动态决定
  D. 派生字段:   DIR, PRM, AFN, length, CS (用户不可填)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent  # wireforge/


# ── BuildTarget ───────────────────────────────────────────────────────

@dataclass
class InputField:
    """用户需提供的输入字段。"""
    name: str
    type: str           # uint8 | bcd | hex | enum | bcd_numeric | struct | bytes ...
    required: bool
    desc: str = ""
    length: int | None = None
    default: Any = None
    enum_values: dict | None = None
    unit: str = ""
    # struct sub-fields
    children: list[InputField] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "type": self.type, "required": self.required}
        if self.desc: d["desc"] = self.desc
        if self.length: d["length"] = self.length
        if self.default is not None: d["default"] = self.default
        if self.enum_values: d["values"] = self.enum_values
        if self.unit: d["unit"] = self.unit
        if self.children: d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class BuildTarget:
    """Resolve 结果——描述一次构造需要的全部信息。"""
    protocol: str
    path: str                           # 路由链
    message_id: str = ""
    variant_id: str = ""
    # A. 目标定位参数
    target_info: dict[str, Any] = field(default_factory=dict)
    # B. 链路/帧上下文 (已有默认值)
    frame_defaults: dict[str, Any] = field(default_factory=dict)
    # C. 业务数据输入 schema
    input_schema: list[InputField] = field(default_factory=list)
    # D. 派生字段 (用户不可填)
    derived_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "path": self.path,
            "message_id": self.message_id,
            "variant_id": self.variant_id,
            "target_info": self.target_info,
            "frame_defaults": self.frame_defaults,
            "input_schema": [f.to_dict() for f in self.input_schema],
            "derived_fields": self.derived_fields,
        }


# ── Resolve ───────────────────────────────────────────────────────────

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


def resolve(target_info: dict[str, Any]) -> BuildTarget:
    """Phase 1: 根据目标信息解析 BuildTarget。

    target_info 示例:
      {"proto": "csg", "di": "E8020701", "intent": "active_report"}
      {"proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "uplink"}

    返回 BuildTarget，其中 input_schema 列出用户需填的字段。
    """
    proto = _proto(target_info.get("proto", "dlt645"))
    _ensure_ir(proto)

    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import BuildEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto}.ir.json"))
    be = BuildEngine(ir, create_builtin_registry())

    # 构建 info dict 用于路由查找
    info: dict[str, Any] = {}
    dn = target_info.get("dir", target_info.get("direction", "downlink"))
    info["direction"] = dn
    if "func" in target_info:
        info["func"] = int(str(target_info["func"]).replace("0x", ""), 16)
    if "afn" in target_info:
        info["afn"] = int(str(target_info["afn"]).replace("0x", ""), 16)
    if "di" in target_info:
        info["di"] = str(target_info["di"])
    if "has_address" in target_info:
        info["has_address"] = target_info["has_address"]

    # 路由查找
    path_info = be.resolve_path(info)
    leaf_id = path_info["leaf_id"]
    leaf = ir.leaves.get(leaf_id)
    if not leaf:
        raise ValueError(f"leaf not found: {leaf_id}")

    # 收集 input_schema: 遍历从叶子到根的所有字段
    input_fields = _collect_input_fields(ir, leaf, leaf_id)
    frame_defaults = _collect_frame_defaults(ir, proto, info)

    # 派生字段 (帧级自动计算)
    derived: dict[str, Any] = {"seq": 0x01}
    dv = 0 if dn == "downlink" else 1
    if proto == "dlt645_2007":
        derived["control"] = {"func": info.get("func", 0x11), "dir": dv, "ack": 0x00, "follow": 0x00}
    else:
        derived["control"] = {"dir": dv, "prm": 0x01 if dv == 0 else 0x00, "add": info.get("has_address", False)}
        derived["afn"] = info.get("afn", 0x00)

    return BuildTarget(
        protocol=proto,
        path=path_info["path_str"],
        message_id=path_info.get("message_id", ""),
        variant_id=leaf.name,
        target_info=target_info,
        frame_defaults=frame_defaults,
        input_schema=input_fields,
        derived_fields=derived,
    )


def _collect_input_fields(ir, leaf, leaf_id) -> list[InputField]:
    """递归收集叶子节点及其子路由的所有用户输入字段。"""
    fields: list[InputField] = []

    for lf in leaf.fields:
        if lf.optional:
            continue
        t = lf.type_ref
        if t == "routed_payload":
            # 递归到子路由
            sub_router = lf.params.get("router", "")
            if sub_router in ir.routers:
                rnode = ir.routers[sub_router]
                for target_id in rnode.route_table.values():
                    if target_id in ir.leaves:
                        sub_leaf = ir.leaves[target_id]
                        fields.extend(_collect_input_fields(ir, sub_leaf, target_id))
        elif t in ("const", "const_repeat", "checksum",
                   "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            continue  # 固定/计算字段
        elif t == "struct":
            # 展开 struct 子字段为扁平 dotted name (如 datetime.second)
            for sf in lf.params.get("fields", []):
                fields.append(InputField(
                    name=f"{lf.name}.{sf.get('name', '?')}",
                    type=sf.get("type", "uint8"),
                    required=True,
                    length=sf.get("length"),
                    desc=sf.get("description", ""),
                ))
        else:
            required = not lf.optional
            extra: dict[str, Any] = {}
            if t == "enum":
                extra["enum_values"] = lf.params.get("values")
            if t == "bcd_numeric":
                extra["unit"] = lf.params.get("unit", "")
            fields.append(InputField(
                name=lf.name, type=t, required=required,
                desc=lf.params.get("description", ""),
                length=lf.length,
                default=lf.default,
                **extra,
            ))

    return fields


def _normalize_di(di: str) -> str:
    """规范化 DI：移除空格/分隔符，统一为大写无空格。"""
    return di.replace(" ", "").replace("-", "").replace(":", "").upper()


def _collect_frame_defaults(ir, proto: str, info: dict) -> dict[str, Any]:
    """收集帧级默认值。"""
    defaults: dict[str, Any] = {"preamble": 4, "address": "000000000001"}
    if proto == "dlt645_2007" and info.get("func") == 0x13:
        dv = 0 if info.get("direction") == "downlink" else 1
        if dv == 0:
            defaults["address"] = "AAAAAAAAAAAA"
    return defaults


# ── From-Frame Decode ──────────────────────────────────────────────────

def decode_frame(hex_text: str, proto: str | None = None) -> dict[str, Any]:
    """从 hex 帧解码出协议、路由和字段值。

    返回: {protocol, path, message_id, values, target_info, frame_hex}
    用于 --from-frame 流程：解码后修改字段再重写 build。
    """
    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine

    cleaned = hex_text.strip().replace(" ", "").replace("\n", "")
    if not cleaned:
        raise ValueError("empty hex frame")

    # 自动检测协议或使用指定协议
    if proto:
        proto_full = _proto(proto)
        _ensure_ir(proto_full)
        ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto_full}.ir.json"))
        engine = DecodeEngine(ir, create_builtin_registry())
        try:
            result = engine.decode(bytes.fromhex(cleaned))
        except Exception:
            raise ValueError(f"decode failed for protocol {proto_full}")
    else:
        # 自动尝试
        for candidate in ("dlt645_2007", "csg_2016"):
            try:
                _ensure_ir(candidate)
                ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{candidate}.ir.json"))
                engine = DecodeEngine(ir, create_builtin_registry())
                result = engine.decode(bytes.fromhex(cleaned))
                proto_full = candidate
                break
            except Exception:
                continue
        else:
            raise ValueError("auto-detect failed: frame not recognized as dlt645 or csg")

    # 从解码值提取 target_info
    values = result.values
    target_info: dict[str, Any] = {"proto": proto_full}

    control = values.get("control", {})
    if isinstance(control, dict):
        if "func" in control:
            target_info["func"] = f"0x{int(control['func']):02X}"
        if "dir" in control:
            dv = control["dir"]
            target_info["dir"] = "downlink" if dv == 0 else "uplink"

    if "afn" in values and not isinstance(values["afn"], dict):
        target_info["afn"] = f"0x{int(values['afn']):02X}"
    if "di" in values and not isinstance(values["di"], dict):
        target_info["di"] = _normalize_di(str(values["di"]))

    # DI/AFN 可能在嵌套的 payload 中（如 read_data_response.di / csg_downlink.afn）
    for key, val in values.items():
        if isinstance(val, dict):
            continue
        # DI: key 以 .di 结尾
        if key.endswith(".di") and "di" not in target_info:
            target_info["di"] = _normalize_di(str(val))
        # AFN: key 以 .afn 结尾
        if key.endswith(".afn") and "afn" not in target_info:
            target_info["afn"] = f"0x{int(val):02X}"
        # func: key 以 .func 结尾，且 control.func 还未提取到时
        if key.endswith(".func") and "func" not in target_info:
            target_info["func"] = f"0x{int(val):02X}"

    # 提取 message_id 从路径: "...→dlt645_2007.read_data_response" → "read_data_response"
    message_id = ""
    parts = result.path_str.split("→")
    if parts:
        last = parts[-1].strip()
        if "." in last:
            message_id = last.rsplit(".", 1)[-1]
        else:
            message_id = last

    return {
        "protocol": proto_full,
        "path": result.path_str,
        "message_id": message_id,
        "values": values,
        "target_info": target_info,
        "frame_hex": result.raw_hex,
    }


# ── Encode ────────────────────────────────────────────────────────────

def encode(target: BuildTarget, user_values: dict[str, Any]) -> str:
    """Phase 2: 根据 BuildTarget 和用户输入构造帧，返回 hex 字符串。"""
    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{target.protocol}.ir.json"))
    be = BuildEngine(ir, create_builtin_registry())
    de = DecodeEngine(ir, create_builtin_registry())

    # 组装 values
    fv = dict(target.frame_defaults)
    fv.update(target.derived_fields)

    # 用户业务字段
    for field in target.input_schema:
        if field.name in user_values:
            fv[field.name] = user_values[field.name]
        elif field.default is not None:
            fv[field.name] = field.default
        elif not field.required:
            pass
        # required but missing → BuildEngine will raise

    # target_info 中的 di / func 等
    ti = target.target_info
    if "di" in ti:
        fv.setdefault("di", ti["di"])
    if "afn" in ti:
        fv.setdefault("afn", int(str(ti["afn"]).replace("0x", ""), 16))
    if "func" in ti:
        fv.setdefault("func", int(str(ti["func"]).replace("0x", ""), 16))

    info = {}
    info["direction"] = ti.get("dir", ti.get("direction", "downlink"))
    if "func" in ti:
        info["func"] = int(str(ti["func"]).replace("0x", ""), 16)
    if "afn" in ti:
        info["afn"] = int(str(ti["afn"]).replace("0x", ""), 16)
    if "di" in ti:
        info["di"] = str(ti["di"])

    # 将 dotted key 嵌套为 struct: datetime.second → {datetime: {second: ...}}
    fv = _nest_dotted(fv)

    r = be.build(fv, info=info)
    de.decode(r.frame)  # 验证
    return r.frame_hex


def _nest_dotted(values: dict[str, Any]) -> dict[str, Any]:
    """将 dotted key 嵌套为 dict。"""
    result: dict[str, Any] = {}
    for key, val in values.items():
        if "." in key:
            parent, child = key.split(".", 1)
            if parent not in result or not isinstance(result[parent], dict):
                result[parent] = {}
            result[parent][child] = val
        else:
            if key not in result:
                result[key] = val
    return result
