"""Deterministic field type inference from FieldCandidate evidence."""

from __future__ import annotations

from typing import Any

from protocol_extend.candidate import FieldCandidate, InferredField
from protocol_extend import evidence_parser as ep


_EXPLICIT_CODEC_TYPES = frozenset({
    "bcd", "ascii", "hex", "bytes", "bitset",
    "uint8", "uint16_le", "uint16_be", "uint24_le", "uint32_le", "uint32_be",
})


def infer_field(candidate: FieldCandidate) -> InferredField:
    if candidate.semantic_override:
        return _apply_override(candidate)

    # Preserve explicit array DSL from agent
    if candidate.agent_type == "array":
        return _infer_array(candidate)

    if candidate.agent_type == "struct" or candidate.subfields:
        return _infer_object(candidate)

    texts = list(candidate.evidence)
    if candidate.desc and candidate.desc not in texts:
        texts.insert(0, candidate.desc)

    value_table = ep.parse_value_table(texts)
    if value_table:
        if ep.is_bool_value_table(value_table, texts):
            return InferredField(
                name=candidate.name,
                desc=candidate.desc,
                semantic_type="bool",
                codec={
                    "type": "enum",
                    "values": _normalize_bool_values(value_table),
                    "length": ep.enum_byte_length(value_table, candidate.bytes),
                },
                confidence="high",
                reasons=["value_table_2_states"],
            )
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="enum",
            codec={
                "type": "enum",
                "values": value_table,
                "length": ep.enum_byte_length(value_table, candidate.bytes),
            },
            confidence="high",
            reasons=["value_table"],
        )

    if ep.has_named_states(texts):
        named = ep.parse_named_states(texts)
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="enum",
            codec={
                "type": "enum",
                "values": named or {0: "状态0", 1: "状态1"},
                "length": candidate.bytes or 1,
            },
            confidence="medium",
            reasons=["named_states"],
            warnings=["enum_hex_values_missing"] if not ep.has_value_table(texts) else [],
        )

    unit = candidate.unit
    scale = candidate.scale
    if not unit and not scale:
        parsed_unit, parsed_scale = ep.parse_unit_scale(texts)
        unit = unit or parsed_unit
        scale = scale if scale is not None else parsed_scale

    lo, hi = candidate.range_min, candidate.range_max
    if lo is None and hi is None:
        lo, hi = ep.parse_range(texts)

    if unit or scale is not None or lo is not None or hi is not None:
        if unit and unit.upper() in {"V", "A", "KW", "KWH", "W", "WH", "HZ", "℃", "°C", "%"}:
            codec = ep.decimal_codec(candidate.bytes, unit)
            return InferredField(
                name=candidate.name,
                desc=candidate.desc,
                semantic_type="decimal",
                codec=codec,
                confidence="high" if unit else "medium",
                reasons=["unit_or_scale"],
            )
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="integer",
            codec={"type": ep.integer_codec_type(candidate.bytes)},
            confidence="medium",
            reasons=["range_or_scale_without_unit"],
        )

    if ep.mentions_ascii(texts) or candidate.agent_type == "ascii":
        length = candidate.extra.get("length") or candidate.bytes or 1
        codec: dict[str, Any] = {"type": "ascii", "length": length}
        if candidate.extra.get("byte_order"):
            codec["byte_order"] = candidate.extra["byte_order"]
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="string",
            codec=codec,
            confidence="high",
            reasons=["ascii_keyword"],
        )

    if ep.mentions_raw(texts):
        length = candidate.extra.get("length") or candidate.bytes
        codec = {"type": "bytes"}
        if length:
            codec["length"] = length
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="raw_hex",
            codec=codec,
            confidence="high",
            reasons=["raw_keyword"],
        )

    if (
        candidate.type_guess in _EXPLICIT_CODEC_TYPES
        and not value_table
        and not ep.has_named_states(texts)
    ):
        codec = _codec_from_explicit(candidate)
        sem = "string" if candidate.type_guess == "ascii" else "raw_hex" if candidate.type_guess in ("hex", "bytes") else "integer"
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type=sem,
            codec=codec,
            confidence="high",
            reasons=["explicit_codec_type"],
        )

    # Fallback: respect explicit scalar type_guess as codec hint only
    if candidate.type_guess and candidate.type_guess not in ("struct", "array"):
        codec: dict[str, Any] = {"type": candidate.type_guess}
        for key in ("length", "default", "unit", "byte_order", "format", "signed"):
            if key in candidate.extra and candidate.extra[key] not in (None, ""):
                codec[key] = candidate.extra[key]
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="integer",
            codec=codec,
            confidence="low",
            reasons=["type_guess_fallback"],
            warnings=["unknown_semantic_used_type_guess"],
        )

    return InferredField(
        name=candidate.name,
        desc=candidate.desc,
        semantic_type="unknown",
        codec={},
        confidence="low",
        reasons=["no_evidence"],
        warnings=["unknown_semantic_type"],
    )


def infer_fields(agent_fields: list[dict[str, Any]]) -> tuple[list[InferredField], list[dict[str, Any]]]:
    """Infer all fields; return (inferred_list, inference_report)."""
    inferred = [infer_field(candidate_from_agent_field(f)) for f in agent_fields]
    report = [inference_entry(inf) for inf in inferred]
    return inferred, report


def candidate_from_agent_field(field: dict[str, Any]) -> FieldCandidate:
    from protocol_extend.candidate import candidate_from_agent_field as _from
    return _from(field)


def inference_entry(inferred: InferredField) -> dict[str, Any]:
    return {
        "name": inferred.name,
        "semantic_type": inferred.semantic_type,
        "codec": dict(inferred.codec),
        "confidence": inferred.confidence,
        "reasons": list(inferred.reasons),
        "warnings": list(inferred.warnings),
        "overridden": inferred.overridden,
    }


def _normalize_bool_values(values: dict[int, str]) -> dict[int, str]:
    keys = sorted(values.keys())
    if keys == [0, 1]:
        return values
    out: dict[int, str] = {}
    for idx, key in enumerate(keys[:2]):
        out[idx] = values[key]
    return out


def _infer_object(candidate: FieldCandidate) -> InferredField:
    sub = candidate.subfields
    children = [infer_field(child) for child in sub] if sub else []
    alias = ep.detect_datetime_alias(sub) if sub else None
    if alias:
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="object",
            codec={"type": alias},
            confidence="high",
            reasons=["datetime_subfields"],
            subfields=children,
        )

    return InferredField(
        name=candidate.name,
        desc=candidate.desc,
        semantic_type="object",
        codec={"type": "struct"},
        confidence="high" if sub else "medium",
        reasons=["subfields"],
        subfields=children,
    )


def _infer_array(candidate: FieldCandidate) -> InferredField:
    item_inferred: InferredField | None = None
    if candidate.item_type == "struct" and candidate.item_fields:
        item_inferred = infer_field(FieldCandidate(
            name=candidate.item_name or "item",
            desc="",
            subfields=candidate.item_fields,
            agent_type="struct",
        ))
    elif candidate.item_type:
        item_inferred = infer_field(FieldCandidate(
            name=candidate.item_name or "item",
            desc="",
            type_guess=candidate.item_type,
            agent_type=candidate.item_type,
            extra=dict(candidate.item_params),
        ))

    codec: dict[str, Any] = {"type": "array"}
    if candidate.count_ref:
        codec["count_ref"] = candidate.count_ref
    if candidate.item_type:
        codec["item_type"] = item_inferred.codec.get("type", candidate.item_type) if item_inferred else candidate.item_type
    if candidate.item_name:
        codec["item_name"] = candidate.item_name

    return InferredField(
        name=candidate.name,
        desc=candidate.desc,
        semantic_type="array",
        codec=codec,
        confidence="high",
        reasons=["array_dsl"],
        subfields=[item_inferred] if item_inferred else [],
    )


def _codec_from_explicit(candidate: FieldCandidate) -> dict[str, Any]:
    codec: dict[str, Any] = {"type": candidate.type_guess}
    for key in ("length", "default", "unit", "byte_order", "format", "signed"):
        if key in candidate.extra and candidate.extra[key] not in (None, ""):
            codec[key] = candidate.extra[key]
    return codec


def _apply_override(candidate: FieldCandidate) -> InferredField:
    override = str(candidate.semantic_override or "").strip().lower()
    reasons = ["manual_override"]

    if override in ("bool",):
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="bool",
            codec={
                "type": "enum",
                "values": {0: "关闭", 1: "打开"},
                "length": candidate.bytes or 1,
            },
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    if override in ("enum",):
        values = ep.parse_value_table(candidate.evidence) or {0: "值0", 1: "值1"}
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="enum",
            codec={
                "type": "enum",
                "values": values,
                "length": ep.enum_byte_length(values, candidate.bytes),
            },
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    if override in ("object", "struct"):
        return _infer_object(candidate)

    if override in ("decimal",):
        codec = ep.decimal_codec(candidate.bytes, candidate.unit)
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="decimal",
            codec=codec,
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    if override in ("string", "ascii"):
        length = candidate.extra.get("length") or candidate.bytes or 1
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="string",
            codec={"type": "ascii", "length": length},
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    if override in ("raw_hex", "bytes", "hex"):
        length = candidate.extra.get("length") or candidate.bytes
        codec: dict[str, Any] = {"type": "bytes"}
        if length:
            codec["length"] = length
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="raw_hex",
            codec=codec,
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    if override in ("integer", "uint8", "uint16_le", "uint24_le", "uint32_le"):
        codec_type = override if override not in ("integer",) else ep.integer_codec_type(candidate.bytes)
        return InferredField(
            name=candidate.name,
            desc=candidate.desc,
            semantic_type="integer",
            codec={"type": codec_type},
            confidence="medium",
            reasons=reasons,
            overridden=True,
        )

    return InferredField(
        name=candidate.name,
        desc=candidate.desc,
        semantic_type="unknown",
        codec={},
        confidence="low",
        reasons=reasons + ["unrecognized_override"],
        warnings=["unknown_semantic_type"],
        overridden=True,
    )
