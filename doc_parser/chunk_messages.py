"""Split DocumentIR into MessageSection chunks for multi-message documents."""

from __future__ import annotations

import re

from doc_parser.document_ir import DocumentIR, MessageSection
from doc_parser.enrich_sections import enrich_all_sections
from doc_parser.metadata_extractor import extract_from_text

_HEADING_RE = re.compile(r"(?:Heading|标题)\s*[1-4]", re.I)
_NUMBERED_TITLE_RE = re.compile(r"^\d+[\.、．]\s*[\u4e00-\u9fffA-Za-z]")
_SECTION_KW = ("数据单元", "报文类型", "报文格式", "应用层报文", "报文定义")
_WEAK_BOUNDARY_KW = ("Fn=", "DI=", "数据标识", "功能码")


def chunk_messages(doc: DocumentIR, *, chapter_hint: str | None = None) -> list[MessageSection]:
    """Build MessageSection list from paragraphs and tables."""
    if not doc.paragraphs and not doc.tables:
        return []

    paragraphs = _filter_paragraphs_by_chapter(doc, chapter_hint)
    sections: list[MessageSection] = []
    current: MessageSection | None = None
    sec_counter = 0

    def _start_section(title: str, para_id: str) -> MessageSection:
        nonlocal sec_counter
        sec_counter += 1
        hints = extract_from_text(title)
        return MessageSection(
            section_id=f"sec_{sec_counter:02d}",
            title=title,
            afn=hints.afn,
            di=hints.di,
            description=title,
            paragraph_ids=[para_id],
            dir_hint=hints.dir_hint,
            add_hint=hints.add_hint,
        )

    for para in paragraphs:
        is_boundary = _is_section_boundary(para)
        if is_boundary:
            if current is not None:
                sections.append(current)
            current = _start_section(para.text, para.id)
        elif current is not None:
            _append_paragraph(current, para)
        elif _looks_like_message_title(para.text):
            current = _start_section(para.text, para.id)

    if current is not None:
        sections.append(current)

    if not sections:
        sections = _sections_from_table_blocks(doc, chapter_hint)

    _assign_tables(doc, sections, paragraphs)
    doc.sections = sections
    enrich_all_sections(doc)
    return doc.sections


def _is_section_boundary(para) -> bool:
    if para.style and _HEADING_RE.search(para.style):
        return True
    if any(kw in para.text for kw in _SECTION_KW):
        return True
    if _NUMBERED_TITLE_RE.match(para.text.strip()):
        return True
    if any(kw in para.text for kw in _WEAK_BOUNDARY_KW) and len(para.text) < 80:
        return True
    return False


def _looks_like_message_title(text: str) -> bool:
    t = text.strip()
    if len(t) < 4 or len(t) > 80:
        return False
    if _NUMBERED_TITLE_RE.match(t):
        return True
    if any(kw in t for kw in ("查询", "上报", "设置", "请求", "响应")) and "表" not in t:
        return True
    return False


def _append_paragraph(section: MessageSection, para) -> None:
    section.paragraph_ids.append(para.id)
    hints = extract_from_text(para.text)
    if hints.afn is not None and section.afn is None:
        section.afn = hints.afn
    if hints.di and not section.di:
        section.di = hints.di
    if hints.dir_hint is not None:
        section.dir_hint = hints.dir_hint
    if hints.add_hint is not None:
        section.add_hint = hints.add_hint


def _filter_paragraphs_by_chapter(doc: DocumentIR, chapter_hint: str | None):
    if not chapter_hint:
        return doc.paragraphs
    hint = chapter_hint.strip()
    in_range = False
    selected = []
    for para in doc.paragraphs:
        if hint in para.text and (para.style and _HEADING_RE.search(para.style or "")):
            in_range = True
            continue
        if in_range and para.style and _HEADING_RE.search(para.style or "") and hint not in para.text:
            break
        if in_range:
            selected.append(para)
    return selected or doc.paragraphs


def _sections_from_table_blocks(doc: DocumentIR, chapter_hint: str | None) -> list[MessageSection]:
    sections: list[MessageSection] = []
    tables = doc.tables
    if chapter_hint:
        # keep all tables if chapter filter cannot map tables; paragraph filter handles scope
        pass
    for idx, table in enumerate(tables):
        title = table.title or f"表格 {table.id}"
        hints = extract_from_text(title)
        hints.merge(extract_from_text(" ".join(" ".join(r) for r in table.rows[:5])))
        if not hints.di and not _looks_like_message_title(title):
            continue
        sections.append(MessageSection(
            section_id=f"sec_{idx + 1:02d}",
            title=title,
            afn=hints.afn,
            di=hints.di,
            description=title,
            table_ids=[table.id],
            dir_hint=hints.dir_hint,
            add_hint=hints.add_hint,
        ))
    return sections


def _assign_tables(doc: DocumentIR, sections: list[MessageSection], paragraphs) -> None:
    if not sections:
        return
    para_to_section: dict[str, MessageSection] = {}
    for sec in sections:
        for pid in sec.paragraph_ids:
            para_to_section[pid] = sec

    for table in doc.tables:
        para_before = (table.provenance or {}).get("paragraph_before")
        target = para_to_section.get(para_before) if para_before else None
        if target is None:
            hints = extract_from_text(" ".join(" ".join(r) for r in table.rows[:3]))
            if hints.di:
                for sec in sections:
                    if sec.di == hints.di:
                        target = sec
                        break
        if target is None and sections:
            target = sections[-1]
        if target is not None and table.id not in target.table_ids:
            target.table_ids.append(table.id)


def apply_sections(doc: DocumentIR, *, chapter_hint: str | None = None) -> DocumentIR:
    doc.sections = chunk_messages(doc, chapter_hint=chapter_hint)
    return doc
