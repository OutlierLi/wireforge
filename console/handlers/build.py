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
    """智能类型转换：hex → int, 数字 → int, 其他保持字符串。"""
    v = value.strip()
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


def handle(args: dict[str, Any]) -> dict:
    from console.build_resolver import resolve, encode, decode_frame

    # ── 解析 --set 参数 ──
    set_overrides = _parse_set_args(args.get("set"))

    # ── 处理 --from-frame ──
    from_frame = args.get("from_frame", args.get("from-frame", ""))
    from_frame = str(from_frame).strip().strip('"').strip("'")

    if from_frame:
        return _handle_from_frame(args, from_frame, set_overrides)

    # ── 正常 build 流程 ──
    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    target_keys = {"proto", "func", "afn", "di", "dir", "address", "intent",
                   "preamble", "seq", "addr", "direction", "has_address",
                   "resolve", "schema", "describe", "from_frame", "from-frame", "set"}
    target_info = {k: v for k, v in args.items() if k in target_keys and v is not None}
    business_values = {k: v for k, v in args.items() if k not in target_keys}

    # 合并 --set 覆盖
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

    has_required = any(f.required for f in target.input_schema)
    if not business_values and has_required:
        required = [f.name for f in target.input_schema if f.required]
        return {
            "success": False,
            "error": "missing required fields",
            "detail": {
                "missing": [{"key": f.name, "type": f.type,
                             "desc": f.desc, "values": f.enum_values}
                            for f in target.input_schema if f.required],
                "hint": "use --resolve to see full input_schema",
            },
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


def _flatten_values(values: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """扁平化解码值：嵌套 dict 展开为 dotted key。"""
    flat: dict[str, Any] = {}
    for k, v in values.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and k not in ("control",):
            flat.update(_flatten_values(v, full_key))
        else:
            flat[full_key] = v
    # 同时保留原始嵌套 key（如 control、di）
    flat.update({k: v for k, v in values.items() if k not in flat})
    return flat
