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
    derived: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "type": self.type, "required": self.required}
        if self.desc: d["desc"] = self.desc
        if self.length: d["length"] = self.length
        if self.default is not None: d["default"] = self.default
        if self.derived: d["derived"] = self.derived
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
    if "dir" in target_info or "direction" in target_info:
        info["direction"] = target_info.get("dir", target_info.get("direction"))
    if "func" in target_info:
        info["func"] = int(str(target_info["func"]).replace("0x", ""), 16)
    if "afn" in target_info:
        info["afn"] = int(str(target_info["afn"]).replace("0x", ""), 16)
    if "di" in target_info:
        info["di"] = str(target_info["di"])
    has_addr = target_info.get("has_address")
    if has_addr is None:
        has_addr = target_info.get("addr")  # shorthand: --addr true/false
    if has_addr is not None:
        # Coerce string "true"/"false" → bool
        if isinstance(has_addr, str):
            has_addr = has_addr.lower() in ("true", "1", "yes")
        info["has_address"] = bool(has_addr)

    # 路由查找
    path_info = be.resolve_path(info)
    if "control.add" in path_info.get("route_vals", {}):
        info["has_address"] = bool(path_info["route_vals"]["control.add"])
    dn = _direction_from_path(path_info, info)
    target_info = dict(target_info)
    if dn:
        target_info.setdefault("dir", dn)
        target_info.setdefault("direction", dn)
    target_info.setdefault("has_address", info.get("has_address", False))
    leaf_id = path_info["leaf_id"]
    leaf = ir.leaves.get(leaf_id)
    if not leaf:
        raise ValueError(f"leaf not found: {leaf_id}")

    # 收集 input_schema: 遍历从叶子到根的所有字段
    msg_name = path_info.get("message_id", "")
    msg_leaf = next((l for l in ir.leaves.values() if l.name == msg_name), None)
    input_fields = _collect_input_fields(ir, leaf, leaf_id, parent_leaf=msg_leaf)
    frame_defaults = _collect_frame_defaults(ir, proto, info)

    # 派生字段 (帧级自动计算)
    derived: dict[str, Any] = {"seq": 0x01}
    dv = 0 if dn == "downlink" else 1
    if proto == "dlt645_2007":
        derived["control"] = {"func": info.get("func", 0x11), "dir": dv, "ack": 0x00, "follow": 0x00}
    else:
        derived["control"] = {"dir": dv, "prm": 0x01 if dv == 0 else 0x00, "add": info.get("has_address", False)}
        derived["afn"] = info.get("afn", 0x00)
    if proto == "csg_2016" and leaf.name == "csg_2016.afn02_add_task":
        derived["payload_length"] = {"from": "payload", "method": "byte_length"}

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


def _collect_input_fields(ir, leaf, leaf_id, parent_leaf=None) -> list[InputField]:
    """递归收集叶子节点及其子路由的所有用户输入字段。

    同时收集父级消息的非路由字段（如 CSG 地址域 address_area）。
    """
    fields: list[InputField] = []
    seen_names: set[str] = set()

    def _add_field(f: InputField) -> None:
        if f.name not in seen_names:
            seen_names.add(f.name)
            fields.append(f)

    # 先收集父级消息的非路由字段
    if parent_leaf is not None:
        for lf in parent_leaf.fields:
            t = lf.type_ref
            if t == "routed_payload":
                continue  # 路由字段走子路由
            if t in ("const", "const_repeat", "checksum",
                     "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
                continue
            if t == "struct":
                for sf in lf.params.get("fields", []):
                    default = sf.get("default")
                    _add_field(InputField(
                        name=f"{lf.name}.{sf.get('name', '?')}",
                        type=sf.get("type", "uint8"),
                        required=default is None,
                        length=sf.get("length"),
                        desc=sf.get("description", ""),
                        default=default,
                    ))
            else:
                # afn, seq, di 等 — 由 derived_fields 处理，这里跳过
                pass

    for lf in leaf.fields:
        if lf.optional and not lf.condition:  # 有条件的不跳过，只是标记为可选
            continue
        has_condition = lf.condition is not None
        t = lf.type_ref
        if t == "routed_payload":
            # 递归到子路由
            sub_router = lf.params.get("router", "")
            if sub_router in ir.routers:
                rnode = ir.routers[sub_router]
                for target_id in rnode.route_table.values():
                    if target_id in ir.leaves:
                        sub_leaf = ir.leaves[target_id]
                        for f in _collect_input_fields(ir, sub_leaf, target_id):
                            _add_field(f)
        elif t in ("const", "const_repeat", "checksum",
                   "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            continue  # 固定/计算字段
        elif t == "struct":
            # 展开 struct 子字段为扁平 dotted name (如 datetime.second)
            # 如果 struct 有条件，子字段标记为不必填
            for sf in lf.params.get("fields", []):
                default = sf.get("default")
                child = _input_field_from_yaml_dict(sf)
                child.name = f"{lf.name}.{child.name}"
                child.required = not has_condition and default is None
                child.default = default
                _add_field(child)
        elif t == "array":
            derive = lf.params.get("derive")
            if derive:
                continue
            required = not lf.optional and not has_condition and lf.default is None
            item_type = lf.params.get("item_type")
            item_params = lf.params.get("item_params") or {}
            desc = lf.params.get("description", "")
            children: list[InputField] = []
            if item_type == "struct":
                children = [_input_field_from_yaml_dict(sf) for sf in item_params.get("fields", [])]
            elif item_type:
                item_name = lf.params.get("item_name") or "item"
                child = _input_field_from_yaml_dict({
                    "name": item_name,
                    "type": item_type,
                    "description": desc,
                    **item_params,
                })
                children = [child]
            _add_field(InputField(
                name=lf.name,
                type="array",
                required=required,
                desc=desc,
                children=children,
            ))
        else:
            derive = lf.params.get("derive")
            if derive:
                continue
            required = not lf.optional and not has_condition and lf.default is None
            extra: dict[str, Any] = {}
            if t == "enum":
                extra["enum_values"] = lf.params.get("values")
            if t == "bcd_numeric":
                extra["unit"] = lf.params.get("unit", "")
            _add_field(InputField(
                name=lf.name, type=t, required=required,
                desc=lf.params.get("description", ""),
                length=lf.length,
                default=lf.default,
                **extra,
            ))

    return fields


def _input_field_from_yaml_dict(field_yaml: dict[str, Any]) -> InputField:
    """Build InputField from a compiled variant field dict."""
    ftype = str(field_yaml.get("type", "uint8"))
    extra: dict[str, Any] = {}
    if ftype == "enum":
        extra["enum_values"] = field_yaml.get("values")
    if ftype == "bcd_numeric":
        extra["unit"] = field_yaml.get("unit", "")
    return InputField(
        name=str(field_yaml.get("name", "?")),
        type=ftype,
        required=field_yaml.get("default") is None,
        length=field_yaml.get("length"),
        desc=str(field_yaml.get("description", field_yaml.get("desc", ""))),
        default=field_yaml.get("default"),
        **extra,
    )


def _direction_from_path(path_info: dict[str, Any], info: dict[str, Any]) -> str:
    direction = info.get("direction")
    if direction in {"downlink", "uplink"}:
        return str(direction)
    route_vals = path_info.get("route_vals") or {}
    raw = route_vals.get("control.dir")
    if raw is None:
        raw = route_vals.get("dir")
    if raw in (0, "0", "downlink"):
        return "downlink"
    if raw in (1, "1", "uplink"):
        return "uplink"
    raise ValueError("direction is required; provide --dir=downlink or --dir=uplink")


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
    # CSG 地址域默认值
    if proto == "csg_2016" and info.get("has_address"):
        defaults["address_area.asrc"] = "000000000000"
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

    fv.update(_derive_field_values(target, fv))

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
    has_addr = ti.get("has_address")
    if has_addr is None:
        has_addr = ti.get("addr")
    if has_addr is not None:
        if isinstance(has_addr, str):
            has_addr = has_addr.lower() in ("true", "1", "yes")
        info["has_address"] = bool(has_addr)

    # 将 dotted key 嵌套为 struct: datetime.second → {datetime: {second: ...}}
    fv = _nest_dotted(fv)

    r = be.build(fv, info=info)
    de.decode(r.frame)  # 验证
    return r.frame_hex


def _derive_field_values(target: BuildTarget, values: dict[str, Any]) -> dict[str, Any]:
    if target.protocol == "csg_2016" and target.variant_id == "csg_2016.afn02_add_task":
        if "payload" in values:
            return {"payload_length": _hex_byte_length(values["payload"])}
    return {}


def _hex_byte_length(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, dict) and "raw" in value:
        value = value["raw"]
    if isinstance(value, str):
        clean = value.replace(" ", "").replace("\n", "").replace("\t", "")
        return len(clean) // 2
    raise ValueError(f"cannot derive byte length from {type(value).__name__}")


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
