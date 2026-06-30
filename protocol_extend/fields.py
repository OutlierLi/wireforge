"""Field DSL normalization, TypeInferencer emit, and YAML generation."""

from __future__ import annotations

from typing import Any

from protocol_extend.candidate import FieldCandidate, InferredField, candidate_from_agent_field
from protocol_extend.domain_types import is_domain_type
from protocol_extend.type_inferencer import infer_field, infer_fields, inference_entry
from protocol_extend.semantic_validator import validate_all, validate_inferred

# Agent-facing field DSL reference (evidence-driven; do not pick uint8 by byte width).
FIELD_DSL_EXAMPLES: list[dict[str, Any]] = [
    {
        "name": "device_type",
        "desc": "设备类型",
        "bytes": 2,
        "evidence": [
            "00H：单相表",
            "01H：三相表",
            "02H：采集器",
            "03H：集中器",
        ],
    },
    {
        "name": "switch_state",
        "desc": "开关",
        "evidence": ["0：关闭", "1：打开"],
    },
    {
        "name": "voltage_a",
        "desc": "A相电压",
        "bytes": 2,
        "evidence": ["单位 0.1V，范围 0~300"],
    },
    {
        "name": "vendor_code",
        "desc": "厂商代码",
        "evidence": ["2字节 ASCII 字符串"],
        "length": 2,
    },
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
            {"name": "address", "type": "node_address", "desc": "地址"},
            {
                "name": "device_type",
                "desc": "设备类型",
                "evidence": ["00H：单相表", "01H：三相表"],
            },
        ],
    },
]

_SCALAR_KEYS = ("length", "desc", "description", "default", "unit", "byte_order", "format", "signed")
_ARRAY_ITEM_SCALAR_KEYS = ("length", "byte_order", "format", "signed")
_ENUM_KEYS = ("values", "length")


def process_agent_fields(
    agent_fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Infer, validate, and emit YAML-ready field dicts."""
    if not agent_fields:
        return [], [], []

    candidates = [candidate_from_agent_field(f) for f in agent_fields]
    inferred_list = [infer_field(c) for c in candidates]
    for inf, cand in zip(inferred_list, candidates):
        inf.warnings = validate_inferred(inf, cand)

    yaml_fields = [field_to_yaml_from_inferred(inf) for inf in inferred_list]
    report = [inference_entry(inf) for inf in inferred_list]
    warnings = validate_all(inferred_list, candidates)
    return yaml_fields, report, warnings


def field_to_yaml(field: dict[str, Any]) -> dict[str, Any]:
    """Convert Agent field DSL dict to variant YAML field entry (via TypeInferencer)."""
    candidate = candidate_from_agent_field(field)
    inferred = infer_field(candidate)
    inferred.warnings = validate_inferred(inferred, candidate)
    return field_to_yaml_from_inferred(inferred)


def field_to_yaml_from_inferred(inferred: InferredField) -> dict[str, Any]:
    """Emit variant YAML field from InferredField — sole write path for inferred scalars."""
    if inferred.semantic_type == "array":
        return _emit_array(inferred)

    out: dict[str, Any] = {"name": inferred.name}
    codec = dict(inferred.codec)

    if inferred.desc:
        out["desc"] = inferred.desc

    if inferred.semantic_type == "object" and codec.get("type") == "struct":
        out["type"] = "struct"
        if inferred.subfields:
            out["fields"] = [field_to_yaml_from_inferred(child) for child in inferred.subfields]
        return out

    field_type = codec.pop("type", "uint8")
    out["type"] = field_type

    for key in _ENUM_KEYS + _SCALAR_KEYS:
        if key in codec and codec[key] not in (None, ""):
            out[key] = codec[key]

    return out


def _emit_array(inferred: InferredField) -> dict[str, Any]:
    codec = inferred.codec
    out: dict[str, Any] = {
        "name": inferred.name,
        "type": "array",
    }
    if inferred.desc:
        out["desc"] = inferred.desc
    if codec.get("count_ref"):
        out["count_ref"] = codec["count_ref"]
    if codec.get("item_name"):
        out["item_name"] = codec["item_name"]

    item_type = codec.get("item_type", "uint8")
    out["item_type"] = item_type

    if inferred.subfields and item_type == "struct":
        struct_inf = inferred.subfields[0]
        inner = struct_inf.subfields or [struct_inf]
        out["item_params"] = {
            "fields": [field_to_yaml_from_inferred(child) for child in inner],
        }
    elif inferred.subfields:
        child = inferred.subfields[0]
        params = {k: v for k, v in child.codec.items() if k != "type"}
        if params:
            out["item_params"] = params
    elif codec.get("item_params"):
        out["item_params"] = dict(codec["item_params"])

    return out


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

        if item_type in {"bcd", "ascii", "hex", "bytes"} and not is_domain_type(item_type):
            params = field.get("item_params") or {}
            length = field.get("length") or params.get("length")
            if length in (None, ""):
                missing.append(f"{path}.item_params.length")

    return missing
