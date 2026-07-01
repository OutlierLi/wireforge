"""decode 命令处理器 — 返回 dict。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent


def handle(args: dict[str, Any]) -> dict:
    from console.arg_utils import normalize_hex_from_args
    from console.build_resolver import _proto, _ensure_ir

    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    hx = normalize_hex_from_args(args)
    if not hx:
        return {
            "success": False,
            "error": "missing required parameter",
            "detail": {
                "missing": [{"key": "hex", "type": "str", "example": "FE FE 68 ... 16"}],
            },
        }

    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto}.ir.json"))
    de = DecodeEngine(ir, create_builtin_registry())

    try:
        frame = bytes.fromhex(hx)
        result = de.decode(frame)
        return {
            "success": True,
            "data": {
                "protocol": proto,
                "path": result.path_str,
                "frame": result.raw_hex,
                "values": {k: v for k, v in result.values.items()
                           if isinstance(v, (str, int, dict)) and not k.startswith(("read_", "csg_"))},
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
