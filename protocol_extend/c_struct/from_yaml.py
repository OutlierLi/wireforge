"""Convert WireForge variant YAML fields to C struct source."""

from __future__ import annotations

import re
from typing import Any

_ALIAS_TYPES = {
    "datetime_ymdhm",
    "datetime_ymdhms",
    "bcd_date_ymd",
    "bcd_time_hms",
    "node_address",
}

_SCALAR_MAP = {
    "uint8": "uint8_t",
    "int8": "int8_t",
    "uint16_le": "uint16_t",
    "int16_le": "int16_t",
    "uint32_le": "uint32_t",
    "int32_le": "int32_t",
    "uint16_be": "uint16_be_t",
    "uint32_be": "uint32_be_t",
}


def render_c_struct_source(
    *,
    struct_name: str,
    fields: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a WireForge C struct .h snippet from YAML field dicts."""
    lines: list[str] = []
    if metadata:
        meta_parts = []
        for key in ("afn", "di", "dir", "add", "desc", "description", "pair"):
            if key not in metadata or metadata[key] in (None, ""):
                continue
            val = metadata[key]
            if key == "dir":
                val = "downlink" if val in (0, "0", "downlink") else "uplink"
            if key == "add":
                val = "true" if val else "false"
            if isinstance(val, str) and (" " in val or "=" in val):
                meta_parts.append(f'{key}="{val}"')
            else:
                meta_parts.append(f"{key}={val}")
        if meta_parts:
            lines.append(f"/* @wireforge {' '.join(meta_parts)} */")

    lines.append("typedef struct __attribute__((packed)) {")
    lines.extend(_render_fields(fields, indent=4))
    lines.append(f"}} {struct_name};")
    return "\n".join(lines) + "\n"


def _render_fields(fields: list[dict[str, Any]], *, indent: int) -> list[str]:
    out: list[str] = []
    pad = " " * indent
    for field in fields:
        out.extend(_render_field(field, pad=pad))
    return out


def _render_field(field: dict[str, Any], *, pad: str) -> list[str]:
    name = str(field.get("name") or "").strip()
    ftype = str(field.get("type") or "uint8")
    desc = str(field.get("description") or field.get("desc") or "").strip()
    annotations: list[str] = []
    if desc:
        annotations.append(f"@desc {desc}")

    if "default" in field:
        default = field["default"]
        if isinstance(default, int) and ftype == "enum":
            annotations.append(f"@default 0x{default:02X}")
        else:
            annotations.append(f"@default {default}")

    if ftype == "struct":
        nested = field.get("fields") or []
        lines = [f"{pad}struct {{"]
        lines.extend(_render_fields(nested, indent=len(pad) + 4))
        lines.append(f"{pad}}} {name};{_comment(annotations)}")
        return lines

    if ftype == "array":
        count_ref = field.get("count_ref")
        item_name = field.get("item_name")
        item_type = str(field.get("item_type") or "uint8")
        item_params = field.get("item_params") or {}
        if count_ref:
            annotations.append(f"@count_ref {count_ref}")
        if item_name:
            annotations.append(f"@item_name {item_name}")
        if item_type == "bcd" and int(item_params.get("length") or 6) == 6:
            annotations.append("@domain node_address")
            return [f"{pad}node_address_t {name}[];{_comment(annotations)}"]
        c_item = _scalar_c_type({"type": item_type, **item_params})
        return [f"{pad}{c_item} {name}[];{_comment(annotations)}"]

    if ftype == "enum":
        values = field.get("values") or {}
        enum_text = " ".join(f"{k}:{v}" for k, v in values.items())
        annotations.append(f"@enum {enum_text}")
        length = field.get("length")
        c_type = "uint16_t" if length == 2 else "uint8_t"
        return [f"{pad}{c_type} {name};{_comment(annotations)}"]

    if ftype in _ALIAS_TYPES:
        if ftype == "node_address":
            annotations.append("@domain node_address")
            return [f"{pad}node_address_t {name};{_comment(annotations)}"]
        annotations.append(f"@alias {ftype}")
        return [f"{pad}uint8_t {name}[{_alias_size(ftype)}];{_comment(annotations)}"]

    if ftype == "hex" and field.get("length_from"):
        annotations.append(f"@length_ref {field['length_from']}")
        annotations.append("@hex")
        return [f"{pad}uint8_t {name}[];{_comment(annotations)}"]

    if ftype == "hex" and field.get("length"):
        annotations.append("@hex")
        return [f"{pad}uint8_t {name}[{int(field['length'])}];{_comment(annotations)}"]

    if ftype == "bytes" and field.get("length_from"):
        annotations.append(f"@length_ref {field['length_from']}")
        return [f"{pad}uint8_t {name}[];{_comment(annotations)}"]

    if ftype == "bytes" and field.get("length"):
        return [f"{pad}uint8_t {name}[{int(field['length'])}];{_comment(annotations)}"]

    if ftype == "ascii" and field.get("length"):
        return [f"{pad}char {name}[{int(field['length'])}];{_comment(annotations)}"]

    if ftype == "bcd":
        params = {k: v for k, v in field.items() if k not in {"name", "type", "description", "desc"}}
        length = int(field.get("length") or 6)
        if length == 6 and field.get("byte_order", "little") == "little":
            annotations.append("@domain node_address")
            return [f"{pad}node_address_t {name};{_comment(annotations)}"]
        annotations.append(f"@alias bcd")
        return [f"{pad}uint8_t {name}[{length}];{_comment(annotations)}"]

    c_type = _scalar_c_type(field)
    return [f"{pad}{c_type} {name};{_comment(annotations)}"]


def _scalar_c_type(field: dict[str, Any]) -> str:
    ftype = str(field.get("type") or "uint8")
    if ftype in _SCALAR_MAP:
        return _SCALAR_MAP[ftype]
    if ftype.endswith("_t"):
        return ftype
    return "uint8_t"


def _alias_size(alias: str) -> int:
    return {
        "datetime_ymdhm": 5,
        "datetime_ymdhms": 6,
        "bcd_date_ymd": 3,
        "bcd_time_hms": 3,
    }.get(alias, 1)


def _comment(annotations: list[str]) -> str:
    if not annotations:
        return ""
    return f" /* {' '.join(annotations)} */"


def slug_from_variant_id(variant_id: str) -> str:
    text = variant_id.split(".", 1)[-1]
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_").lower()
    return text or "payload"


def struct_name_from_variant_id(variant_id: str) -> str:
    return f"{slug_from_variant_id(variant_id)}_t"
