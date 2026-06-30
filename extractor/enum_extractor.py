"""Extract evidence lines from table cell text (enum/bool patterns)."""

from __future__ import annotations

import re

_HEX_ENUM = re.compile(
    r"(?:0x)?([0-9A-Fa-f]{1,4})H?\s*[：:\-—]\s*([^；;,\n]+)",
    re.I,
)
_DEC_ENUM = re.compile(r"\b(\d+)\s*[：:\-—]\s*([^；;,\n]+)")
_SPLIT = re.compile(r"[；;\n]")


def build_evidence_from_desc(desc: str) -> list[str]:
    """Turn free-text description into evidence lines for TypeInferencer."""
    if not desc or not desc.strip():
        return []

    evidence: list[str] = []
    for part in _SPLIT.split(desc):
        part = part.strip()
        if not part:
            continue
        m = _HEX_ENUM.search(part)
        if m:
            evidence.append(f"{int(m.group(1), 16):02X}H：{m.group(2).strip()}")
            continue
        m2 = _DEC_ENUM.search(part)
        if m2:
            evidence.append(f"{m2.group(1)}：{m2.group(2).strip()}")
            continue

    if evidence:
        return evidence

    # Whole desc as single evidence line for keyword-based inferencer
    return [desc.strip()]
