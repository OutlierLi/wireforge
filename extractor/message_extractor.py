"""Extract ExtensionDraft from DocumentIR + MessageSection."""

from __future__ import annotations

from doc_parser.document_ir import DocumentIR, MessageSection
from extractor.extension_draft import ExtensionDraft
from extractor.field_extractor import (
    classify_table,
    extract_fields_from_table,
    extract_meta_from_table,
)


def extract_message(doc: DocumentIR, section: MessageSection) -> ExtensionDraft:
    draft = ExtensionDraft(
        afn=section.afn,
        di=section.di or "",
        description=section.description or section.title,
        dir=section.dir_hint,
        add=section.add_hint,
        section_id=section.section_id,
    )

    report: list[dict] = []
    all_fields: list[dict] = []

    for tid in section.table_ids:
        table = doc.table_by_id(tid)
        if not table:
            continue
        kind = classify_table(table)
        report.append({"table_id": tid, "kind": kind, "title": table.title, "rows": len(table.rows)})

        if kind == "meta":
            meta = extract_meta_from_table(table)
            if meta.get("afn") is not None and draft.afn is None:
                draft.afn = meta["afn"]
            if meta.get("di") and not draft.di:
                draft.di = meta["di"]
            if meta.get("dir") is not None and draft.dir is None:
                draft.dir = meta["dir"]
            if meta.get("add") is not None and draft.add is None:
                draft.add = meta["add"]
            continue

        if kind == "app_function":
            report.append({"table_id": tid, "kind": kind, "title": table.title, "rows": len(table.rows)})
            continue

        if kind == "field":
            fields = extract_fields_from_table(table)
            all_fields.extend(fields)
            report.append({"table_id": tid, "fields_extracted": len(fields)})

    # Also scan section paragraphs for inline metadata
    for pid in section.paragraph_ids:
        para = doc.paragraph_by_id(pid)
        if not para:
            continue
        from doc_parser.parse_docx import extract_afn_di_from_text
        afn, di = extract_afn_di_from_text(para.text)
        if afn is not None and draft.afn is None:
            draft.afn = afn
        if di and not draft.di:
            draft.di = di

    draft.fields = all_fields
    draft.extraction_report = report
    return draft
