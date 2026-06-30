"""Emit WireForge variant YAML field dicts from CStructDef."""

from __future__ import annotations

from typing import Any

from protocol_extend.c_struct.ir import CFieldDef, CStructDef
from protocol_extend.c_struct.type_map import scalar_yaml_type


def c_struct_to_yaml_fields(
    defn: CStructDef,
    *,
    desc_key: str = "desc",
) -> list[dict[str, Any]]:
    return [_field_to_yaml(f, desc_key=desc_key) for f in defn.fields]


def _apply_desc(out: dict[str, Any], field: CFieldDef, *, desc_key: str) -> None:
    if field.annotations.desc:
        out[desc_key] = field.annotations.desc


def _apply_default(out: dict[str, Any], field: CFieldDef) -> None:
    if field.annotations.default not in (None, ""):
        raw = field.annotations.default
        if raw.lower().startswith("0x"):
            try:
                out["default"] = int(raw, 16)
            except ValueError:
                out["default"] = raw
        elif raw.isdigit():
            out["default"] = int(raw)
        else:
            out["default"] = raw


def _field_to_yaml(field: CFieldDef, *, desc_key: str = "desc") -> dict[str, Any]:
    if field.is_flexible_array and field.annotations.length_ref:
        out: dict[str, Any] = {"name": field.name}
        if field.annotations.hex_type:
            out["type"] = "hex"
        else:
            out["type"] = "bytes"
        out["length_from"] = field.annotations.length_ref
        _apply_desc(out, field, desc_key=desc_key)
        return out

    if field.is_flexible_array:
        return _array_to_yaml(field, desc_key=desc_key)

    if field.is_array and not field.subfields:
        collapsed = _collapse_fixed_scalar_array(field, desc_key=desc_key)
        if collapsed is not None:
            return collapsed
        return _array_to_yaml(field, desc_key=desc_key)

    if field.subfields:
        out: dict[str, Any] = {
            "name": field.name,
            "type": "struct",
            "fields": [_field_to_yaml(child, desc_key=desc_key) for child in field.subfields],
        }
        _apply_desc(out, field, desc_key=desc_key)
        return out

    if field.annotations.enum_values:
        out = {
            "name": field.name,
            "type": "enum",
            "values": dict(field.annotations.enum_values),
        }
        _apply_desc(out, field, desc_key=desc_key)
        length = field.wire_size or 1
        if length != 1:
            out["length"] = length
        _apply_default(out, field)
        return out

    codec = scalar_yaml_type(field.c_type, annotations=field.annotations)
    out = {"name": field.name, **codec}
    _apply_desc(out, field, desc_key=desc_key)
    _apply_default(out, field)

    if field.c_type == "char" and field.array_size:
        out["type"] = "ascii"
        out["length"] = field.array_size
    elif field.c_type in {"uint8_t", "uint8"} and field.array_size:
        if field.annotations.hex_type:
            out["type"] = "hex"
        else:
            out["type"] = "bytes"
        out["length"] = field.array_size

    return out


def _collapse_fixed_scalar_array(field: CFieldDef, *, desc_key: str = "desc") -> dict[str, Any] | None:
    """Map ``uint8_t name[N]`` with @alias bcd / @hex to a single typed field."""
    if field.array_size is None or field.is_flexible_array:
        return None

    ann = field.annotations
    length = field.array_size

    if ann.alias == "bcd" or ann.domain in {"bcd", "bcd_datetime"}:
        out: dict[str, Any] = {"name": field.name, "type": "bcd", "length": length}
        _apply_desc(out, field, desc_key=desc_key)
        return out

    if field.c_type in {"uint8_t", "uint8"}:
        if ann.hex_type:
            out = {"name": field.name, "type": "hex", "length": length}
        else:
            out = {"name": field.name, "type": "bytes", "length": length}
        _apply_desc(out, field, desc_key=desc_key)
        return out

    return None


def _array_to_yaml(field: CFieldDef, *, desc_key: str = "desc") -> dict[str, Any]:
    ann = field.annotations
    out: dict[str, Any] = {
        "name": field.name,
        "type": "array",
    }
    _apply_desc(out, field, desc_key=desc_key)
    if ann.count_ref:
        out["count_ref"] = ann.count_ref
    if ann.item_name:
        out["item_name"] = ann.item_name
    if field.array_size is not None and not field.is_flexible_array:
        out["length"] = field.array_size

    if field.subfields:
        out["item_type"] = "struct"
        out["item_params"] = {
            "fields": [_field_to_yaml(child, desc_key=desc_key) for child in field.subfields],
        }
        return out

    item_codec = scalar_yaml_type(field.c_type, annotations=ann)
    item_type = item_codec.pop("type", "uint8")
    out["item_type"] = item_type
    params = {k: v for k, v in item_codec.items() if k != "name"}
    if params:
        out["item_params"] = params
    return out
