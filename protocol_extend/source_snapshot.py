"""Immutable source snapshots for fidelity checking (DOCX section or manual input)."""

from __future__ import annotations

import copy
import re
from typing import Any

from doc_parser.document_ir import DocumentIR, MessageSection
from extractor.extension_draft import ExtensionDraft
from extractor.field_extractor import classify_table, extract_meta_from_table

_NUMBER_PREFIX = re.compile(r"^\d+[\.、]\s*")


def _deep_copy_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(fields)


def build_source_snapshot_from_section(
    doc: DocumentIR,
    section: MessageSection,
    draft: ExtensionDraft,
) -> dict[str, Any]:
    """Freeze original document content for a message section."""
    paragraphs: list[dict[str, str]] = []
    for pid in section.paragraph_ids:
        para = doc.paragraph_by_id(pid)
        if para and para.text.strip():
            paragraphs.append({"id": para.id, "text": para.text.strip()})

    meta_rows: list[list[str]] = []
    field_rows: list[dict[str, Any]] = []

    for tid in section.table_ids:
        table = doc.table_by_id(tid)
        if not table:
            continue
        kind = classify_table(table)
        if kind == "meta":
            meta_rows.extend([list(row) for row in table.rows])
            continue
        if kind == "field":
            for field in draft.fields:
                prov = field.get("provenance") or {}
                if prov.get("table_id") == tid:
                    field_rows.append({
                        "table_id": tid,
                        "name": field.get("name", ""),
                        "desc": field.get("desc", ""),
                        "bytes": field.get("bytes"),
                        "evidence": list(field.get("evidence") or []),
                        "raw_row": list(prov.get("raw_row") or []),
                    })
            if not field_rows:
                for row_idx, row in enumerate(table.rows):
                    field_rows.append({
                        "table_id": tid,
                        "name": row[0] if row else "",
                        "desc": row[-1] if len(row) > 2 else "",
                        "bytes": None,
                        "evidence": [],
                        "raw_row": list(row),
                        "row_index": row_idx,
                    })

    return {
        "source": "docx",
        "section_id": section.section_id,
        "title": section.title or draft.title,
        "description": section.description or draft.description,
        "afn": draft.afn,
        "di": (draft.di or section.di or "").upper(),
        "dir_hint": section.dir_hint if section.dir_hint is not None else draft.dir,
        "add_hint": section.add_hint if section.add_hint is not None else draft.add,
        "metadata_confidence": section.metadata_confidence,
        "metadata_sources": list(section.metadata_sources or []),
        "paragraphs": paragraphs,
        "meta_rows": meta_rows,
        "field_rows": field_rows,
        "fields": _deep_copy_fields(draft.fields),
        "resp_fields": _deep_copy_fields(draft.resp_fields),
    }


def build_source_snapshot_from_draft(draft: ExtensionDraft) -> dict[str, Any]:
    """Freeze manual / parsed input as source baseline."""
    return {
        "source": "manual",
        "section_id": draft.section_id or None,
        "title": draft.description or draft.title,
        "description": draft.description or draft.title,
        "afn": draft.afn,
        "di": (draft.di or "").upper(),
        "dir_hint": draft.dir,
        "add_hint": draft.add,
        "metadata_confidence": "low",
        "metadata_sources": ["manual_input"],
        "paragraphs": [],
        "meta_rows": [],
        "field_rows": [
            {
                "name": f.get("name", ""),
                "desc": f.get("desc", ""),
                "bytes": f.get("bytes"),
                "evidence": list(f.get("evidence") or []),
                "raw_row": list((f.get("provenance") or {}).get("raw_row") or []),
            }
            for f in draft.fields
        ],
        "fields": _deep_copy_fields(draft.fields),
        "resp_fields": _deep_copy_fields(draft.resp_fields),
    }


def freeze_snapshot_if_missing(
    draft: ExtensionDraft,
    *,
    doc: DocumentIR | None = None,
    section: MessageSection | None = None,
) -> None:
    """Set source_snapshot once; never overwrite on modify."""
    if draft.source_snapshot:
        return
    if doc is not None and section is not None:
        draft.source_snapshot = build_source_snapshot_from_section(doc, section, draft)
    else:
        draft.source_snapshot = build_source_snapshot_from_draft(draft)


def source_excerpt(snapshot: dict[str, Any], *, max_field_rows: int = 10) -> dict[str, Any]:
    """Compact excerpt for Agent-facing MCP payloads."""
    if not snapshot:
        return {}
    field_rows = snapshot.get("field_rows") or []
    return {
        "source": snapshot.get("source"),
        "title": snapshot.get("title"),
        "description": snapshot.get("description"),
        "di": snapshot.get("di"),
        "afn": f"{snapshot['afn']:02X}" if snapshot.get("afn") is not None else None,
        "dir_hint": snapshot.get("dir_hint"),
        "add_hint": snapshot.get("add_hint"),
        "metadata_confidence": snapshot.get("metadata_confidence"),
        "meta_rows": (snapshot.get("meta_rows") or [])[:5],
        "paragraphs": (snapshot.get("paragraphs") or [])[:3],
        "field_rows": field_rows[:max_field_rows],
        "field_count": len(field_rows),
    }


def normalize_description(text: str) -> str:
    text = _NUMBER_PREFIX.sub("", (text or "").strip().lower())
    return re.sub(r"\s+", "", text)
