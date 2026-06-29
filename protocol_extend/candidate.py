"""FieldCandidate / InferredField models for TypeInferencer pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldCandidate:
    name: str
    desc: str = ""
    bytes: int | None = None
    evidence: list[str] = field(default_factory=list)
    subfields: list[FieldCandidate] = field(default_factory=list)
    unit: str | None = None
    scale: float | None = None
    range_min: float | None = None
    range_max: float | None = None
    type_guess: str | None = None
    semantic_override: str | None = None
    # Preserved agent DSL for array/struct/array metadata
    agent_type: str | None = None
    count_ref: str | None = None
    item_type: str | None = None
    item_name: str | None = None
    item_fields: list[FieldCandidate] = field(default_factory=list)
    item_params: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def all_text(self) -> str:
        parts = [self.desc, *self.evidence]
        return "\n".join(p for p in parts if p)


@dataclass
class InferredField:
    name: str
    desc: str
    semantic_type: str  # enum|bool|object|integer|decimal|string|raw_hex|unknown|array
    codec: dict[str, Any]
    confidence: str  # high|medium|low
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    overridden: bool = False
    subfields: list[InferredField] = field(default_factory=list)


def _parse_evidence(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [str(raw)]


def _parse_range(raw: Any) -> tuple[float | None, float | None]:
    if raw is None:
        return None, None
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return None, None
    text = str(raw).strip()
    for sep in ("~", "～", "-", "—", "至", "到"):
        if sep in text:
            parts = text.split(sep, 1)
            try:
                return float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                return None, None
    return None, None


def candidate_from_agent_field(field: dict[str, Any]) -> FieldCandidate:
    """Parse Agent field DSL dict into FieldCandidate."""
    name = str(field.get("name") or "").strip()
    desc = str(field.get("desc") or field.get("description") or "").strip()
    evidence = _parse_evidence(field.get("evidence"))
    if not evidence and desc:
        evidence = [desc]

    agent_type = str(field.get("type") or field.get("type_guess") or "").strip() or None
    lo, hi = _parse_range(field.get("range"))

    subfields: list[FieldCandidate] = []
    if isinstance(field.get("fields"), list):
        subfields = [candidate_from_agent_field(child) for child in field["fields"]]

    item_fields: list[FieldCandidate] = []
    raw_item_fields = field.get("item_fields") or (field.get("item_params") or {}).get("fields")
    if isinstance(raw_item_fields, list):
        item_fields = [candidate_from_agent_field(child) for child in raw_item_fields]

    bytes_val = field.get("bytes")
    if bytes_val is not None:
        try:
            bytes_val = int(bytes_val)
        except (TypeError, ValueError):
            bytes_val = None

    scale = field.get("scale")
    if scale is not None:
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = None

    extra: dict[str, Any] = {}
    for key in ("length", "default", "byte_order", "format", "signed", "values"):
        if key in field and field[key] not in (None, ""):
            extra[key] = field[key]

    return FieldCandidate(
        name=name,
        desc=desc,
        bytes=bytes_val,
        evidence=evidence,
        subfields=subfields,
        unit=field.get("unit"),
        scale=scale,
        range_min=lo,
        range_max=hi,
        type_guess=agent_type,
        semantic_override=field.get("semantic_override"),
        agent_type=agent_type,
        count_ref=field.get("count_ref"),
        item_type=field.get("item_type"),
        item_name=field.get("item_name"),
        item_fields=item_fields,
        item_params=dict(field.get("item_params") or {}),
        extra=extra,
    )
