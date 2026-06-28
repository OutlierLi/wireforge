"""Field DSL normalization, validation, and YAML emission for protocol extensions."""

from __future__ import annotations

from typing import Any

# Agent-facing field DSL reference (also surfaced in INPUT_SCHEMA).
FIELD_DSL_EXAMPLES: list[dict[str, Any]] = [
    {"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"},
    {
        "name": "node_count",
        "type": "uint8",
        "desc": "节点数量",
    },
    {
        "name": "nodes",
        "type": "array",
        "count_ref": "node_count",
        "item_type": "struct",
        "item_name": "node",
        "desc": "节点列表",
        "item_fields": [
            {"name": "address", "type": "bcd", "length": 6, "byte_order": "little", "desc": "地址"},
            {"name": "device_type", "type": "uint8", "desc": "设备类型"},
        ],
    },
    {
        "name": "node_addrs",
        "type": "array",
        "count_ref": "node_count",
        "item_type": "bcd",
        "item_name": "node_addr",
        "item_params": {"length": 6, "byte_order": "little"},
        "desc": "节点地址列表",
    },
]

_SCALAR_KEYS = ("length", "desc", "description", "default", "unit", "byte_order", "format", "signed")
_ARRAY_ITEM_SCALAR_KEYS = ("length", "byte_order", "format", "signed")


def field_to_yaml(field: dict[str, Any]) -> dict[str, Any]:
    """Convert Agent field DSL dict to variant YAML field entry."""
    field_type = field.get("type", "uint8")
    out: dict[str, Any] = {"name": field["name"], "type": field_type}

    for key in _SCALAR_KEYS:
        if key in field and field[key] not in (None, ""):
            yaml_key = "desc" if key == "description" else key
            out[yaml_key] = field[key]

    if field_type == "struct" and isinstance(field.get("fields"), list):
        out["fields"] = [field_to_yaml(child) for child in field["fields"]]
        return out

    if field_type != "array":
        return out

    count_ref = field.get("count_ref")
    if count_ref:
        out["count_ref"] = count_ref

    item_type = field.get("item_type")
    if item_type:
        out["item_type"] = item_type

    item_name = field.get("item_name")
    if item_name:
        out["item_name"] = item_name

    item_params = _array_item_params(field, item_type or "")
    if item_params:
        out["item_params"] = item_params

    return out


def _array_item_params(field: dict[str, Any], item_type: str) -> dict[str, Any]:
    params = dict(field.get("item_params") or {})

    if item_type == "struct":
        sub_fields = field.get("item_fields") or params.get("fields")
        if isinstance(sub_fields, list) and sub_fields:
            params["fields"] = [field_to_yaml(child) for child in sub_fields]
        return params

    for key in _ARRAY_ITEM_SCALAR_KEYS:
        if key in field and field[key] not in (None, "") and key not in params:
            params[key] = field[key]
    return params


def missing_field_metadata(fields: list[dict[str, Any]], *, prefix: str = "fields") -> list[str]:
    """Return missing name/desc/array metadata paths for a field list."""
    missing: list[str] = []
    names = [str(field.get("name", "")).strip() for field in fields]

    for idx, field in enumerate(fields):
        path = f"{prefix}[{idx}]"
        name = names[idx]
        if not name:
            missing.append(f"{path}.name")
            continue

        if not (field.get("desc") or field.get("description")):
            missing.append(f"{path}.desc")

        field_type = field.get("type", "uint8")
        if field_type == "struct" and isinstance(field.get("fields"), list):
            missing.extend(missing_field_metadata(field["fields"], prefix=f"{path}.fields"))
            continue

        if field_type != "array":
            continue

        count_ref = str(field.get("count_ref") or "").strip()
        if not count_ref:
            missing.append(f"{path}.count_ref")
        elif count_ref not in names[:idx]:
            missing.append(f"{path}.count_ref")

        item_type = str(field.get("item_type") or "").strip()
        if not item_type:
            missing.append(f"{path}.item_type")
            continue

        if item_type == "struct":
            sub_fields = field.get("item_fields") or (field.get("item_params") or {}).get("fields")
            if not isinstance(sub_fields, list) or not sub_fields:
                missing.append(f"{path}.item_fields")
            else:
                missing.extend(missing_field_metadata(sub_fields, prefix=f"{path}.item_fields"))
            continue

        if item_type in {"bcd", "ascii", "hex", "bytes"}:
            params = field.get("item_params") or {}
            length = field.get("length") or params.get("length")
            if length in (None, ""):
                missing.append(f"{path}.item_params.length")

    return missing
