"""DOCX ingestion pipeline for protocol_extend state machine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doc_parser.chunk_messages import apply_sections
from doc_parser.di_catalog import build_di_catalog, resolve_di_candidate, section_for_candidate
from doc_parser.document_ir import DocumentIR, MessageSection
from doc_parser.parse_docx import parse_docx, resolve_docx_path
from doc_parser.metadata_extractor import resolve_afn
from extractor.field_extractor import classify_table, extract_fields_from_table
from extractor.extension_draft import ExtensionDraft
from extractor.message_extractor import extract_message
from protocol_extend.schema import ExtensionSpec
from protocol_extend.source_snapshot import freeze_snapshot_if_missing


def document_path_from(record_spec: dict[str, Any], user_input: dict[str, Any]) -> str | None:
    path = user_input.get("document_path") or record_spec.get("document_path")
    return str(path).strip() if path else None


def chapter_hint_from(record_spec: dict[str, Any], user_input: dict[str, Any]) -> str | None:
    hint = user_input.get("chapter_hint") or record_spec.get("chapter_hint")
    return str(hint).strip() if hint else None


def section_id_from(record_spec: dict[str, Any], user_input: dict[str, Any]) -> str | None:
    sid = user_input.get("section_id") or record_spec.get("section_id")
    return str(sid).strip() if sid else None


def candidate_id_from(record_spec: dict[str, Any], user_input: dict[str, Any]) -> str | None:
    cid = user_input.get("candidate_id") or record_spec.get("candidate_id")
    return str(cid).strip() if cid else None


def load_or_parse_document(
    path: str,
    *,
    run_dir: Path,
    root: Path,
    force_reparse: bool = False,
    chapter_hint: str | None = None,
) -> DocumentIR:
    ir_path = run_dir / "document_ir.json"
    if ir_path.exists() and not force_reparse and not chapter_hint:
        cached = DocumentIR.from_dict(json.loads(ir_path.read_text(encoding="utf-8")))
        if cached.sections:
            return cached

    resolved = resolve_docx_path(path, root=root)
    doc = parse_docx(resolved)
    apply_sections(doc, chapter_hint=chapter_hint)
    ir_path.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def build_document_catalog(doc: DocumentIR) -> list[dict[str, Any]]:
    """DI-centric catalog for user selection (title + DI + inferred AFN)."""
    return build_di_catalog(doc)


def catalog_scan_summary(catalog: list[dict[str, Any]]) -> dict[str, int]:
    ready = sum(1 for c in catalog if c.get("ready_to_extend"))
    missing_afn = sum(1 for c in catalog if "afn" in (c.get("missing") or []))
    return {
        "total": len(catalog),
        "ready": ready,
        "missing_afn": missing_afn,
        "missing_di": sum(1 for c in catalog if "di" in (c.get("missing") or [])),
    }


def message_candidates(doc: DocumentIR) -> list[dict[str, Any]]:
    return build_document_catalog(doc)


def resolve_section(
    doc: DocumentIR,
    *,
    section_id: str | None = None,
    di: str | None = None,
    candidate_id: str | None = None,
) -> MessageSection | None:
    if candidate_id or di:
        entry = resolve_di_candidate(doc, candidate_id=candidate_id, di=di)
        if entry:
            return section_for_candidate(doc, entry)

    if section_id:
        return doc.section_by_id(section_id)
    if di:
        di_upper = di.upper().replace(" ", "")
        for sec in doc.sections:
            if sec.di and sec.di.upper() == di_upper:
                return sec
    if len(doc.sections) == 1:
        return doc.sections[0]
    return None


def apply_section_to_spec(doc: DocumentIR, section: MessageSection, spec: ExtensionSpec) -> dict[str, Any]:
    """Extract fields from section and merge into spec; return extraction_report."""
    draft = extract_message(doc, section)
    merged = draft.merge_into_user_input()

    if draft.afn is not None:
        spec.afn = draft.afn
    if draft.di:
        spec.di = draft.di
    if draft.description:
        spec.description = draft.description
    if draft.dir is not None:
        spec.dir = draft.dir
    elif section.dir_hint is not None:
        spec.dir = section.dir_hint
    if draft.add is not None:
        spec.add = draft.add
    elif section.add_hint is not None:
        spec.add = section.add_hint
    if draft.fields and not spec.fields:
        spec.fields = draft.fields
    if draft.resp_fields and not spec.resp_fields:
        spec.resp_fields = draft.resp_fields
    if draft.pair:
        spec.pair = True
    if draft.resp_description:
        spec.resp_description = draft.resp_description

    if spec.afn is None and spec.di:
        afn, _ = resolve_afn(di=spec.di, text=spec.description or section.title)
        if afn is not None:
            spec.afn = afn

    return {
        "section_id": section.section_id,
        "extraction_report": draft.extraction_report,
        "fields_count": len(draft.fields),
        "merged_keys": list(merged.keys()),
    }


def _parse_catalog_afn(afn_raw: Any) -> int | None:
    if afn_raw is None:
        return None
    text = str(afn_raw).strip()
    if not text:
        return None
    try:
        return int(text, 16) if not text.isdigit() else int(text)
    except ValueError:
        return None


def collect_all_drafts(doc: DocumentIR) -> list[ExtensionDraft]:
    """Phase 1: extract raw metadata + fields for every catalog entry (no inference/YAML)."""
    catalog = build_di_catalog(doc)
    drafts: list[ExtensionDraft] = []
    seen_di: set[str] = set()

    for entry in catalog:
        di = str(entry.get("di") or "").upper()
        if not di or di in seen_di:
            continue
        seen_di.add(di)

        section = section_for_candidate(doc, entry)
        if section is None:
            continue

        draft = extract_message(doc, section)
        draft.candidate_id = str(entry.get("candidate_id") or "")
        draft.section_id = str(entry.get("section_id") or section.section_id)
        draft.title = str(entry.get("title") or section.title or draft.description)

        if draft.afn is None:
            draft.afn = _parse_catalog_afn(entry.get("afn"))
        if draft.dir is None and entry.get("dir_hint") is not None:
            draft.dir = int(entry["dir_hint"])
        if draft.add is None and entry.get("add_hint") is not None:
            draft.add = bool(entry["add_hint"])

        if draft.afn is None and draft.di:
            afn, _ = resolve_afn(di=draft.di, text=draft.description or draft.title)
            if afn is not None:
                draft.afn = afn

        if draft.add is None:
            draft.add = section.add_hint if section.add_hint is not None else False
        if draft.dir is None and section.dir_hint is not None:
            draft.dir = section.dir_hint

        freeze_snapshot_if_missing(draft, doc=doc, section=section)
        drafts.append(draft)

    if not drafts and doc.sections:
        for section in doc.sections:
            if section.di and section.di.upper() not in seen_di:
                draft = extract_message(doc, section)
                draft.section_id = section.section_id
                draft.title = section.title or draft.description
                if draft.add is None:
                    draft.add = section.add_hint if section.add_hint is not None else False
                if draft.dir is None and section.dir_hint is not None:
                    draft.dir = section.dir_hint
                freeze_snapshot_if_missing(draft, doc=doc, section=section)
                drafts.append(draft)

    return drafts


def draft_from_user_input(spec: ExtensionSpec) -> ExtensionDraft:
    """Phase 1: assemble a single draft from parsed/manual input."""
    return ExtensionDraft.from_spec(spec, title=spec.description)


def save_drafts(run_dir: Path, drafts: list[ExtensionDraft]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = [d.to_dict() for d in drafts]
    (run_dir / "drafts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_drafts(run_dir: Path) -> list[ExtensionDraft]:
    path = run_dir / "drafts.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [ExtensionDraft.from_dict(item) for item in data]


def collection_summary(drafts: list[ExtensionDraft]) -> dict[str, int]:
    return {
        "total": len(drafts),
        "ready": sum(1 for d in drafts if not d.missing_fields()),
        "missing_params": sum(1 for d in drafts if d.missing_fields()),
        "pending": sum(1 for d in drafts if d.status == "pending"),
        "accepted": sum(1 for d in drafts if d.status == "accepted"),
        "skipped": sum(1 for d in drafts if d.status == "skipped"),
        "failed": sum(1 for d in drafts if d.status == "failed"),
    }


def review_progress(drafts: list[ExtensionDraft], draft_index: int) -> dict[str, int]:
    return {
        "current": min(draft_index + 1, len(drafts)) if drafts else 0,
        "total": len(drafts),
        "accepted": sum(1 for d in drafts if d.status == "accepted"),
        "skipped": sum(1 for d in drafts if d.status == "skipped"),
        "failed": sum(1 for d in drafts if d.status == "failed"),
        "index": draft_index,
    }


def batch_summary(drafts: list[ExtensionDraft]) -> dict[str, Any]:
    accepted = [d for d in drafts if d.status == "accepted"]
    items = []
    confidences: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for d in drafts:
        item: dict[str, Any] = {
            "di": d.di,
            "status": d.status,
            "extension_file": d.extension_file or None,
            "skip_reason": d.skip_reason or None,
            "last_error": d.last_error or None,
        }
        fr = d.fidelity_report or {}
        if fr:
            item["fidelity_confidence"] = fr.get("confidence")
            item["fidelity_score"] = fr.get("score")
            item["fidelity_summary"] = fr.get("summary")
            conf = fr.get("confidence")
            if conf in confidences:
                confidences[conf] += 1
        items.append(item)
    return {
        "total": len(drafts),
        "accepted": len(accepted),
        "skipped": sum(1 for d in drafts if d.status == "skipped"),
        "failed": sum(1 for d in drafts if d.status == "failed"),
        "files": [d.extension_file for d in accepted if d.extension_file],
        "items": items,
        "fidelity_summary": confidences,
    }


def build_agent_context(
    fields: list[dict[str, Any]],
    doc: DocumentIR | None,
    inference_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build minimal context snippets for unknown fields — not full document."""
    unknown_names = {
        e["name"] for e in inference_report if e.get("semantic_type") == "unknown"
    }
    if not unknown_names or not doc:
        return []

    contexts: list[dict[str, Any]] = []
    for field in fields:
        name = field.get("name", "")
        if name not in unknown_names:
            continue
        prov = field.get("provenance") or {}
        ctx: dict[str, Any] = {
            "field": name,
            "question": "请判断 semantic_type 或补充 evidence / semantic_override",
        }
        if prov.get("table_id"):
            table = doc.table_by_id(prov["table_id"])
            ctx["table_row"] = {
                "table_id": prov["table_id"],
                "row": prov.get("raw_row"),
                "table_title": table.title if table else None,
            }
        if prov.get("row_index") is not None and field.get("desc"):
            ctx["desc"] = field.get("desc")
        contexts.append(ctx)
    return contexts
