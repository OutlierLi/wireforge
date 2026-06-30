"""Post-process MessageSection list with metadata enrichment."""

from __future__ import annotations

from doc_parser.document_ir import DocumentIR, MessageSection
from doc_parser.metadata_extractor import MetadataHints, extract_from_table_rows, extract_from_text, resolve_afn


def _di_headers_from_rows(rows: list[list[str]]) -> list[str]:
    if rows and rows[0] and rows[0][0].strip().upper() in {"DI3", "数据标识编码"}:
        return rows[0]
    return []


def enrich_section(doc: DocumentIR, section: MessageSection) -> MessageSection:
    hints = MetadataHints()

    for pid in section.paragraph_ids:
        para = doc.paragraph_by_id(pid)
        if para:
            hints.merge(extract_from_text(para.text, source=f"paragraph:{pid}"))

    for tid in section.table_ids:
        table = doc.table_by_id(tid)
        if table:
            hints.merge(extract_from_table_rows(table.rows, headers=table.headers or _di_headers_from_rows(table.rows)))

    hints.finalize()
    if hints.afn is None and hints.di:
        afn, source = resolve_afn(
            di=hints.di,
            text=section.title or section.description,
            dir_hint=hints.dir_hint,
        )
        if afn is not None:
            hints.afn = afn
            hints.sources.append(source or "di_derived_afn")

    if hints.afn is not None:
        section.afn = hints.afn
    if hints.di:
        section.di = hints.di
    if hints.dir_hint is not None:
        section.dir_hint = hints.dir_hint
    if hints.add_hint is not None:
        section.add_hint = hints.add_hint
    if not section.description and section.title:
        section.description = section.title

    section.metadata_confidence = hints.confidence
    section.metadata_sources = list(hints.sources)
    section.missing_metadata = hints.missing_fields()
    return section


def enrich_all_sections(doc: DocumentIR) -> DocumentIR:
    doc.sections = [enrich_section(doc, s) for s in doc.sections]
    return doc
