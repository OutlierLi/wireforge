"""build 命令处理器 — 返回 dict。"""

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


def handle(args: dict[str, Any]) -> dict:
    from console.build_resolver import resolve, encode

    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    # 区分定位参数和业务参数
    target_keys = {"proto", "func", "afn", "di", "dir", "address", "intent",
                   "preamble", "seq", "addr", "direction", "has_address",
                   "resolve", "schema", "describe"}
    target_info = {k: v for k, v in args.items() if k in target_keys and v is not None}
    business_values = {k: v for k, v in args.items() if k not in target_keys}

    # Resolve
    try:
        target = resolve(target_info)
    except Exception as e:
        return {"success": False, "error": str(e)}

    # --resolve
    if args.get("resolve") or args.get("schema") or args.get("describe"):
        return {
            "success": True,
            "data": target.to_dict(),
        }

    # 合并定位参数中的业务字段
    schema_names = {f.name for f in target.input_schema}
    for k, v in target_info.items():
        if k in schema_names and k not in business_values:
            business_values[k] = v

    # 检查必填字段
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

    # Encode
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
