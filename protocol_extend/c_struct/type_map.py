"""Map C types to WireForge YAML codec types."""

from __future__ import annotations

from typing import Any

SCALAR_WIRE_SIZES: dict[str, int] = {
    "uint8_t": 1,
    "int8_t": 1,
    "uint16_t": 2,
    "int16_t": 2,
    "uint32_t": 4,
    "int32_t": 4,
    "char": 1,
}

DOMAIN_TYPES: dict[str, str] = {
    "node_address_t": "node_address",
    "node_address": "node_address",
    "bcd_datetime_t": "bcd_datetime",
    "bcd_datetime": "bcd_datetime",
}

ALIAS_TYPES: set[str] = {
    "datetime_ymdhm",
    "datetime_ymdhms",
    "bcd_date_ymd",
    "bcd_time_hms",
}


def wire_size_for_scalar(c_type: str, *, array_size: int | None = None) -> int | None:
    base = SCALAR_WIRE_SIZES.get(c_type.strip())
    if base is None:
        if c_type in DOMAIN_TYPES or c_type in ALIAS_TYPES:
            return 6 if c_type == "node_address_t" else None
        if c_type.endswith("_t") and c_type.replace("_t", "") in ALIAS_TYPES:
            return None
    if base is None:
        return None
    if array_size is not None:
        return base * array_size
    return base


def scalar_yaml_type(c_type: str, *, annotations: Any = None) -> dict[str, Any]:
    """Return YAML field fragment for a scalar C type."""
    ann = annotations
    domain = getattr(ann, "domain", "") if ann else ""
    alias = getattr(ann, "alias", "") if ann else ""
    unit = getattr(ann, "unit", "") if ann else ""
    hex_type = getattr(ann, "hex_type", False) if ann else False

    if domain:
        return {"type": domain}
    if alias:
        return {"type": alias}

    clean = c_type.strip()
    if clean in DOMAIN_TYPES:
        return {"type": DOMAIN_TYPES[clean]}
    if clean in ALIAS_TYPES:
        return {"type": clean}

    if unit:
        length = wire_size_for_scalar(clean) or 2
        fmt = "XXX.X" if length == 2 else "XXXXXX.XX" if length == 4 else "XXX.XXX"
        out: dict[str, Any] = {
            "type": "bcd_numeric",
            "length": length,
            "format": fmt,
            "signed": clean.startswith("int"),
        }
        if unit:
            out["unit"] = unit
        return out

    mapping = {
        "uint8_t": "uint8",
        "int8_t": "int8",
        "uint16_t": "uint16_le",
        "int16_t": "int16_le",
        "uint32_t": "uint32_le",
        "int32_t": "int32_le",
    }
    if clean in mapping:
        return {"type": mapping[clean]}

    if clean == "char":
        return {"type": "ascii"}

    if hex_type:
        return {"type": "hex"}

    return {"type": clean}
