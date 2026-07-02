"""为 protocol_map 条目生成 build / frame 示例（bootstrap 阶段）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

_ROUTE_OR_FRAME_KEYS = frozenset({
    "afn", "seq", "di", "fn", "preamble", "address", "control",
})

_SKIP_SET_PREFIXES = ("control.",)


def enrich_csg_protocol_map(
    protocol_map: dict[str, Any],
    *,
    compiled_dir: str | Path | None = None,
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """为 CSG protocol_map 每条 entry 写入 build_example / frame_example / build_args。"""
    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

    if defaults is None:
        from tests.protocol_info import CSG_FIELD_DEFAULTS
        defaults = CSG_FIELD_DEFAULTS

    base = Path(compiled_dir) if compiled_dir else ROOT / "compiled"
    ir_path = base / "csg_2016.ir.json"
    if not ir_path.exists():
        return protocol_map, [f"missing IR: {ir_path}"]

    ir = ProtocolIR.from_json_file(str(ir_path))
    build_engine = BuildEngine(ir, create_builtin_registry())
    decode_engine = DecodeEngine(ir, create_builtin_registry())

    errors: list[str] = []
    csg = (protocol_map.get("protocols") or {}).get("csg_2016")
    if not csg:
        return protocol_map, ["csg_2016 not found in protocol map"]

    for entry in csg.get("entries") or []:
        try:
            example = _build_csg_entry_example(entry, ir, build_engine, decode_engine, defaults)
        except Exception as exc:
            errors.append(f"{entry.get('entry_id', entry.get('name', '?'))}: {exc}")
            continue
        entry["build_example"] = example["build_example"]
        entry["frame_example"] = example["frame_example"]
        entry["build_args"] = example["build_args"]

    return protocol_map, errors


def _build_csg_entry_example(
    entry: dict[str, Any],
    ir,
    build_engine,
    decode_engine,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    from tests.protocol_build_utils import auto_fill_leaf_fields

    rp = entry.get("route_params") or {}
    info = {
        "direction": rp.get("dir", "downlink"),
        "afn": int(str(rp.get("afn", "00")).replace("0x", ""), 16),
        "di": str(rp.get("di", "")).replace(" ", "").upper(),
        "has_address": bool(rp.get("has_address", False)),
    }
    path = build_engine.resolve_path(info)
    leaf = ir.leaves.get(path["leaf_id"])
    if leaf is None:
        raise ValueError(f"leaf not found: {path['leaf_id']}")

    fv: dict[str, Any] = {
        "afn": info["afn"],
        "seq": 1,
        "di": info["di"],
    }
    if info["has_address"]:
        fv["address_area"] = {
            "asrc": defaults.get("address_area.asrc", "000000000000"),
            "adst": defaults.get("address_area.adst", "012400038813"),
        }

    fv = auto_fill_leaf_fields(leaf, defaults, fv, ir=ir)
    result = build_engine.build(fv, info=info)
    decode_engine.decode(result.frame)

    build_args = _select_build_set_args(fv, entry.get("fields") or [], info["has_address"])
    return {
        "build_example": format_build_example(rp, build_args),
        "frame_example": result.frame_hex,
        "build_args": build_args,
    }


def format_build_example(route_params: dict[str, Any], set_args: dict[str, Any]) -> str:
    """生成可复制的 /build CLI 示例。"""
    parts = [
        "/build",
        "--proto=csg",
        f'--afn={route_params.get("afn", "")}',
        f'--di={route_params.get("di", "")}',
        f'--dir={route_params.get("dir", "downlink")}',
    ]
    if route_params.get("has_address"):
        parts.append("--addr=true")
    for key in sorted(set_args):
        parts.append(f"--set {key}={_format_cli_value(set_args[key])}")
    return " ".join(parts)


def _format_cli_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if 0 <= value <= 0xFF:
            return f"0x{value:02X}"
        return str(value)
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    if isinstance(value, dict):
        if set(value) == {"raw"} or set(value) <= {"raw", "unit"}:
            return str(value.get("raw", ""))
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _flatten_field_values(values: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, val in values.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            if set(val.keys()) <= {"raw", "unit"}:
                flat[full_key] = val
            elif all(isinstance(v, (str, int)) for v in val.values()):
                flat.update(_flatten_field_values(val, full_key))
            else:
                flat[full_key] = val
        else:
            flat[full_key] = val
    return flat


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, dict):
        return {str(k): _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    return value


def _select_build_set_args(
    field_values: dict[str, Any],
    entry_fields: list[str],
    has_address: bool,
) -> dict[str, Any]:
    flat = _flatten_field_values(field_values)
    field_names = set(entry_fields or [])
    out: dict[str, Any] = {}

    for key, val in flat.items():
        if key in _ROUTE_OR_FRAME_KEYS:
            continue
        if any(key.startswith(prefix) for prefix in _SKIP_SET_PREFIXES):
            continue
        if not has_address and key.startswith("address_area."):
            continue
        if field_names:
            matched = key in field_names or any(
                other.startswith(f"{key}.") or key.startswith(f"{other}.")
                for other in field_names
            )
            if not matched:
                continue
        if isinstance(val, dict) and "raw" in val:
            out[key] = val["raw"]
        else:
            out[key] = val
    return _json_safe_value(out)
