"""Validate inferred fields against evidence — prevent semantic downgrade."""

from __future__ import annotations

from protocol_extend.candidate import FieldCandidate, InferredField
from protocol_extend import evidence_parser as ep

_BARE_CODEC_TYPES = frozenset({
    "uint8", "uint16_le", "uint16_be", "uint24_le", "uint32_le", "bytes", "hex",
})


def validate_inferred(inferred: InferredField, candidate: FieldCandidate) -> list[str]:
    warnings: list[str] = list(inferred.warnings)

    if ep.has_value_table(candidate.evidence):
        codec_type = inferred.codec.get("type", "")
        if inferred.semantic_type not in ("enum", "bool", "raw_hex") and codec_type in _BARE_CODEC_TYPES:
            warnings.append(
                f"{candidate.name}: evidence has value table but codec is bare {codec_type} (downgrade blocked)"
            )
        if inferred.semantic_type == "raw_hex" and not ep.mentions_raw(candidate.evidence):
            warnings.append(f"{candidate.name}: raw_hex without raw/transparent keywords")

    if inferred.semantic_type == "unknown" and not candidate.semantic_override:
        warnings.append(f"{candidate.name}: unknown semantic_type — provide evidence or semantic_override")

    if inferred.semantic_type in ("enum", "bool"):
        values = inferred.codec.get("values") or {}
        if not values:
            warnings.append(f"{candidate.name}: enum/bool values empty — fill before production use")
        elif "enum_hex_values_missing" in inferred.warnings:
            warnings.append(f"{candidate.name}: enum labels without hex mapping — confirm values")

    return _dedupe(warnings)


def validate_all(
    inferred_list: list[InferredField],
    candidates: list[FieldCandidate],
) -> list[str]:
    warnings: list[str] = []
    for inf, cand in zip(inferred_list, candidates):
        warnings.extend(validate_inferred(inf, cand))
    return _dedupe(warnings)


def has_unknown_without_override(
    inferred_list: list[InferredField],
    candidates: list[FieldCandidate],
) -> bool:
    for inf, cand in zip(inferred_list, candidates):
        if inf.semantic_type == "unknown" and not cand.semantic_override:
            return True
    return False


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
