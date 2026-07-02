"""build 命令处理器 — 支持 --from-frame 从已有报文修改重写。

用法:
  /build --proto=dlt645 --func=0x11 --di=00010000           # 新构造
  /build --proto=dlt645 --func=0x11 --di=00010000 --resolve # 仅解析 schema
  /build --from-frame="68 ... 16"                            # 解码后重建
  /build --from-frame="68 ... 16" --set di=00020000          # 解码后修改字段再重建
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from console.arg_utils import coerce_business_values, parse_bracket_list

ROOT = Path(__file__).resolve().parent.parent.parent


def _proto(name: str) -> str:
    m = {"dlt645": "dlt645_2007", "csg": "csg_2016"}
    return m.get(name, name)


def _ensure_ir(proto: str):
    ip = ROOT / "compiled" / f"{proto}.ir.json"
    if not ip.exists():
        from protocol_tool.compiler.pipeline import compile_protocol
        reg = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
        compile_protocol(str(reg), proto, output_dir=str(ROOT / "compiled"))


def _parse_set_args(raw: str | list[str] | None) -> dict[str, Any]:
    """解析 --set key=value 参数。

    支持:
      --set di=00020000
      --set freeze_year=26
      多个值: args['set'] = ['di=00020000', 'freeze_year=26']
    """
    if not raw:
        return {}
    items = [raw] if isinstance(raw, str) else raw
    result: dict[str, Any] = {}
    for item in items:
        item = str(item).strip()
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            # 尝试智能类型转换
            result[key] = _smart_coerce(value)
        else:
            # 无 = 的视为布尔标志
            result[item] = True
    return result


def _smart_coerce(value: str) -> Any:
    """智能类型转换：hex → int, 数字 → int, bracket list → list, 其他保持字符串。"""
    v = value.strip()
    parsed = parse_bracket_list(v)
    if parsed is not None:
        return parsed
    if v.lower().startswith("0x"):
        try:
            return int(v, 16)
        except ValueError:
            return v
    # 纯数字 → int
    if v.isdigit() and len(v) <= 2:
        try:
            return int(v)
        except ValueError:
            return v
    return v


_BUILD_TARGET_KEYS = frozenset({
    "proto", "func", "afn", "di", "dir", "address", "intent",
    "preamble", "seq", "addr", "direction", "has_address",
    "resolve", "schema", "describe", "from_frame", "from-frame", "set",
})
_BUILD_BASE_RESERVED = frozenset({"sub", "_"})


def build_frame_from_args(
    args: dict[str, Any],
    *,
    extra_reserved: frozenset[str] | None = None,
) -> dict:
    """构造协议帧（与 ``/build`` 相同逻辑）。供 ``/serial send --build`` 等复用。"""
    from console.build_resolver import resolve, encode

    set_overrides = _parse_set_args(args.get("set"))
    from_frame = args.get("from_frame", args.get("from-frame", ""))
    from_frame = str(from_frame).strip().strip('"').strip("'")
    if from_frame:
        return _handle_from_frame(args, from_frame, set_overrides)

    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    reserved = _BUILD_TARGET_KEYS | _BUILD_BASE_RESERVED | (extra_reserved or frozenset())
    target_info = {k: v for k, v in args.items() if k in _BUILD_TARGET_KEYS and v is not None}
    business_values = {k: v for k, v in args.items() if k not in reserved}
    business_values.update(set_overrides)

    try:
        target = resolve(target_info)
    except Exception as e:
        return {"success": False, "error": str(e)}

    if args.get("resolve") or args.get("schema") or args.get("describe"):
        return {"success": True, "data": target.to_dict()}

    schema_names = {f.name for f in target.input_schema}
    for k, v in target_info.items():
        if k in schema_names and k not in business_values:
            business_values[k] = v
    if (
        "payload" in business_values
        and "payload_length" in schema_names
        and "payload_length" not in business_values
    ):
        from console.build_resolver import _hex_byte_length
        business_values["payload_length"] = _hex_byte_length(business_values["payload"])

    try:
        business_values = coerce_business_values(business_values, target.input_schema)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    unknown_fields = [k for k in business_values if k not in schema_names]
    missing_required = [
        f for f in target.input_schema
        if f.required and f.name not in business_values
    ]

    if unknown_fields or missing_required:
        detail: dict[str, Any] = {
            "input_schema": [f.to_dict() for f in target.input_schema],
            "required_step": "route",
            "hint": "必须先调用 /route 获取正确的字段 schema，然后按 schema 填充字段值",
        }
        if unknown_fields:
            detail["unknown_fields"] = unknown_fields
            detail["error"] = (
                f"未识别的字段: {', '.join(unknown_fields)}。"
                "字段名已变更，请通过 /route 确认当前 schema"
            )
        if missing_required:
            detail["missing_required"] = [f.name for f in missing_required]
            if not unknown_fields:
                detail["error"] = "缺少必填字段，请通过 /route 确认当前 schema"
        return {
            "success": False,
            "status": "route_required",
            "error": detail.get("error", "字段不匹配，请先调用 /route"),
            "detail": detail,
            "path": target.path,
        }

    try:
        frame_hex = encode(target, business_values)
        return {
            "success": True,
            "data": {
                "protocol": target.protocol,
                "path": target.path,
                "frame": frame_hex,
                "resolved": {
                    "message_id": target.message_id,
                    "variant_id": target.variant_id,
                },
            },
        }
    except Exception as e:
        err = str(e)
        import re
        missing = re.findall(r"Required field '(\w+)'", err)
        detail = {
            "input_schema": [f.to_dict() for f in target.input_schema],
            "required_step": "route",
            "hint": "必须先调用 /route 获取正确的字段 schema，然后按 schema 填充字段值",
        }
        if missing:
            detail["missing_required"] = missing
        return {
            "success": False,
            "status": "route_required",
            "error": err,
            "detail": detail,
            "path": target.path,
        }


def handle(args: dict[str, Any]) -> dict:
    return build_frame_from_args(args)


def _handle_from_frame(args: dict[str, Any], hex_text: str, set_overrides: dict) -> dict:
    """--from-frame 流程: decode → modify → rebuild"""
    from console.build_resolver import resolve, encode, decode_frame

    user_proto = args.get("proto", "")
    user_proto = user_proto.strip() if user_proto else ""

    # 1. 解码帧
    try:
        decoded = decode_frame(hex_text, proto=user_proto or None)
    except Exception as e:
        return {"success": False, "error": f"decode from-frame failed: {e}"}

    # 2. 用解码值构造 target_info
    target_info = decoded["target_info"]
    if user_proto:
        target_info["proto"] = user_proto
    # 保留用户额外指定的定位参数
    for key in ("dir", "direction", "func", "afn", "di"):
        if key in args and args[key] is not None:
            target_info[key] = args[key]

    proto = _proto(target_info.get("proto", "dlt645"))
    target_info["proto"] = proto
    _ensure_ir(proto)

    # 3. Resolve
    try:
        target = resolve(target_info)
    except Exception as e:
        return {"success": False, "error": f"resolve from-frame failed: {e}"}

    # --resolve 模式：返回 schema + 解码值
    if args.get("resolve") or args.get("schema") or args.get("describe"):
        return {
            "success": True,
            "data": {
                **target.to_dict(),
                "from_frame": decoded["frame_hex"],
                "decoded_values": _flatten_values(decoded["values"]),
                "set_overrides": set_overrides,
            },
        }

    # 4. 合并业务值：解码值 → --set 覆盖 → 用户直传参数
    business_values = _flatten_values(decoded["values"])
    _merge_raw_payload_from_decode(business_values, decoded["values"])
    business_values.update(set_overrides)

    # 用户可能通过 --di / --func 等参数直接覆盖
    schema_names = {f.name for f in target.input_schema}
    target_keys = {"proto", "func", "afn", "di", "dir", "address", "intent",
                   "preamble", "seq", "addr", "direction", "has_address",
                   "resolve", "schema", "describe", "from_frame", "from-frame", "set"}
    for k, v in args.items():
        if k in target_keys:
            continue
        if k in schema_names:
            business_values[k] = v

    try:
        business_values = coerce_business_values(business_values, target.input_schema)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # 确保 target_info 中的关键字段存在
    ti = target.target_info
    if "di" in ti:
        business_values.setdefault("di", ti["di"])
    if "afn" in ti:
        v = ti.get("afn", "")
        if isinstance(v, str) and v.startswith("0x"):
            business_values.setdefault("afn", int(v, 16))
        elif v:
            business_values.setdefault("afn", int(v) if isinstance(v, str) else v)
    if "func" in ti:
        v = ti.get("func", "")
        if isinstance(v, str) and v.startswith("0x"):
            business_values.setdefault("func", int(v, 16))
        elif v:
            business_values.setdefault("func", int(v) if isinstance(v, str) else v)

    # 5. Encode
    try:
        frame_hex = encode(target, business_values)
        return {
            "success": True,
            "data": {
                "protocol": target.protocol,
                "path": target.path,
                "frame": frame_hex,
                "from_frame": decoded["frame_hex"],
                "resolved": {"message_id": target.message_id, "variant_id": target.variant_id},
            },
        }
    except Exception as e:
        err = str(e)
        import re
        missing = re.findall(r"Required field '(\w+)'", err)
        detail: dict = {}
        if missing:
            detail["missing"] = [{"key": m} for m in missing]
            detail["hint"] = "use --resolve to see input_schema"
        return {"success": False, "error": err, "detail": detail, "path": target.path}


def _merge_raw_payload_from_decode(flat: dict[str, Any], values: dict[str, Any]) -> None:
    """从未识别变体的嵌套解码值中提取 raw/hex 数据域到 di_payload / data_content。"""
    def _walk(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else k
                if k in ("di_payload", "data_content", "di_data") and isinstance(v, (bytes, bytearray)):
                    flat[k] = v.hex().upper()
                    flat[key] = v.hex().upper()
                elif isinstance(v, dict):
                    _walk(v, key)
                elif isinstance(v, (bytes, bytearray)) and k in ("di_payload", "data_content", "di_data"):
                    flat[k] = v.hex().upper()
                    flat[key] = v.hex().upper()
        return None

    _walk(values)
    for k, v in values.items():
        if k.endswith(".di_payload") and isinstance(v, (bytes, bytearray)):
            flat["di_payload"] = v.hex().upper()
        if k.endswith(".data_content") and isinstance(v, (bytes, bytearray)):
            flat["data_content"] = v.hex().upper()
        if k.endswith(".di_data") and isinstance(v, (bytes, bytearray)):
            flat["di_data"] = v.hex().upper()


def _format_decode_value(v: Any) -> Any:
    """将解码值格式化为 JSON/CLI 友好形式。"""
    if isinstance(v, (bytes, bytearray)):
        return v.hex().upper()
    return v


def _flatten_values(values: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """扁平化解码值：嵌套 dict 展开为 dotted key。"""
    flat: dict[str, Any] = {}
    for k, v in values.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and k not in ("control",):
            flat.update(_flatten_values(v, full_key))
        elif isinstance(v, (bytes, bytearray)):
            flat[full_key] = v.hex().upper()
        else:
            flat[full_key] = v
    # 同时保留原始嵌套 key（如 control、di）
    for k, v in values.items():
        if k not in flat:
            flat[k] = _format_decode_value(v)
    return flat

