"""Build DI-centric message catalog from DocumentIR for user selection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from doc_parser.document_ir import DocumentIR, MessageSection
from doc_parser.metadata_extractor import (
    extract_di_from_row,
    extract_di_from_text,
    infer_add_from_text,
    infer_dir_from_text,
    normalize_di_token,
    resolve_afn,
)
from extractor.field_extractor import is_payload_field_table

_TITLE_SKIP_RE = re.compile(r"^(表格|表)\s*\d+", re.I)
_GENERIC_TITLE_RE = re.compile(r"^(应用功能|数据单元|报文格式|数据标识内容)")


@dataclass
class DiCandidate:
    candidate_id: str
    di: str
    title: str
    description: str = ""
    afn: int | None = None
    afn_source: str = ""
    dir_hint: int | None = None
    add_hint: bool | None = None
    section_id: str | None = None
    table_id: str | None = None
    row_index: int | None = None
    field_table_ids: list[str] = field(default_factory=list)
    metadata_confidence: str = "low"
    metadata_sources: list[str] = field(default_factory=list)
    origin: str = "unknown"
    ready_to_extend: bool = True

    def to_catalog_entry(self) -> dict[str, Any]:
        missing: list[str] = []
        if not self.di:
            missing.append("di")
            self.ready_to_extend = False
        if self.afn is None:
            missing.append("afn")
        return {
            "candidate_id": self.candidate_id,
            "section_id": self.section_id,
            "di": self.di,
            "title": self.title,
            "description": self.description or self.title,
            "afn": f"{self.afn:02X}" if self.afn is not None else None,
            "afn_source": self.afn_source or None,
            "dir_hint": self.dir_hint,
            "add_hint": self.add_hint,
            "table_id": self.table_id,
            "field_table_ids": list(self.field_table_ids),
            "confidence": self.metadata_confidence,
            "metadata_sources": list(self.metadata_sources),
            "missing": missing,
            "ready_to_extend": bool(self.di),
        }


def build_di_catalog(doc: DocumentIR) -> list[dict[str, Any]]:
    """Scan document for DI records; return deduplicated catalog with titles."""
    by_di: dict[str, DiCandidate] = {}
    counter = 0

    def _add(record: DiCandidate) -> None:
        nonlocal counter
        if not record.di:
            return
        di = record.di.upper()
        record.di = di
        record.afn, record.afn_source = resolve_afn(
            di=di,
            afn=record.afn,
            text=f"{record.title} {record.description}",
            dir_hint=record.dir_hint,
        )
        if record.dir_hint is None:
            record.dir_hint = infer_dir_from_text(f"{record.title} {record.description}")
        if record.add_hint is None:
            record.add_hint = infer_add_from_text(f"{record.title} {record.description}")
        record.ready_to_extend = True
        existing = by_di.get(di)
        if existing is None or _should_replace(existing, record):
            if not record.candidate_id:
                counter += 1
                record.candidate_id = f"cand_{counter:03d}"
            by_di[di] = record
        elif record.section_id and not existing.section_id:
            existing.section_id = record.section_id
        elif record.field_table_ids:
            for tid in record.field_table_ids:
                if tid not in existing.field_table_ids:
                    existing.field_table_ids.append(tid)

    for table in doc.tables:
        di_headers = _di_headers(table)
        for row_index, row in enumerate(table.rows):
            if _is_di_header_row(row):
                continue
            parsed = extract_di_from_row(row, headers=di_headers)
            if parsed is None:
                continue
            title = parsed.title or _title_from_table(table.title)
            if not title or _is_weak_title(title):
                title = _title_from_table(table.title) or title or parsed.di
            _add(DiCandidate(
                candidate_id="",
                di=parsed.di,
                title=title,
                description=title,
                afn=parsed.afn,
                afn_source=parsed.afn_source,
                dir_hint=parsed.dir_hint,
                add_hint=parsed.add_hint,
                table_id=table.id,
                row_index=row_index,
                metadata_confidence=parsed.confidence,
                metadata_sources=list(parsed.sources),
                origin="table_row",
            ))

        title_di = extract_di_from_text(table.title or "", source="table_title")
        if title_di.di:
            title = _clean_di_from_title(table.title or "") or table.title or title_di.di
            _add(DiCandidate(
                candidate_id="",
                di=title_di.di,
                title=title,
                description=title,
                afn=title_di.afn,
                afn_source="table_title",
                dir_hint=title_di.dir_hint,
                table_id=table.id,
                metadata_confidence=title_di.confidence,
                metadata_sources=list(title_di.sources),
                origin="table_title",
            ))

    for sec in doc.sections:
        if not sec.di:
            continue
        _add(DiCandidate(
            candidate_id="",
            di=sec.di,
            title=_section_title(sec),
            description=sec.description or sec.title,
            afn=sec.afn,
            afn_source="section",
            dir_hint=sec.dir_hint,
            add_hint=sec.add_hint,
            section_id=sec.section_id,
            table_id=sec.table_ids[0] if sec.table_ids else None,
            metadata_confidence=sec.metadata_confidence,
            metadata_sources=list(sec.metadata_sources or []),
            origin="section",
        ))

    for para in doc.paragraphs:
        hints = extract_di_from_text(para.text, source=f"paragraph:{para.id}")
        if not hints.di:
            continue
        title = _clean_di_from_title(para.text) or para.text.strip()
        _add(DiCandidate(
            candidate_id="",
            di=hints.di,
            title=title,
            description=title,
            afn=hints.afn,
            afn_source="paragraph",
            dir_hint=hints.dir_hint,
            metadata_confidence=hints.confidence,
            metadata_sources=list(hints.sources),
            origin="paragraph",
        ))

    candidates = list(by_di.values())
    _link_sections(doc, candidates)
    _link_field_tables(doc, candidates)
    candidates.sort(key=lambda c: (c.di, c.title))
    for idx, cand in enumerate(candidates, start=1):
        cand.candidate_id = f"cand_{idx:03d}"
    return [c.to_catalog_entry() for c in candidates]


def resolve_di_candidate(
    doc: DocumentIR,
    *,
    candidate_id: str | None = None,
    di: str | None = None,
) -> dict[str, Any] | None:
    catalog = build_di_catalog(doc)
    if candidate_id:
        for entry in catalog:
            if entry.get("candidate_id") == candidate_id:
                return entry
    if di:
        di_upper = di.upper().replace(" ", "")
        for entry in catalog:
            if entry.get("di", "").upper() == di_upper:
                return entry
    return None


def section_for_candidate(doc: DocumentIR, entry: dict[str, Any]) -> MessageSection | None:
    """Build MessageSection for field extraction from a catalog entry."""
    sec = doc.section_by_id(entry["section_id"]) if entry.get("section_id") else None
    table_ids = list(entry.get("field_table_ids") or [])
    if entry.get("table_id") and entry["table_id"] not in table_ids:
        table_ids.insert(0, entry["table_id"])

    if sec:
        merged_tables = list(dict.fromkeys(list(sec.table_ids) + table_ids))
        return MessageSection(
            section_id=sec.section_id,
            title=entry.get("title") or sec.title,
            afn=_parse_afn(entry.get("afn")) or sec.afn,
            di=entry.get("di") or sec.di,
            description=entry.get("description") or sec.description,
            paragraph_ids=list(sec.paragraph_ids),
            table_ids=merged_tables,
            dir_hint=entry.get("dir_hint") if entry.get("dir_hint") is not None else sec.dir_hint,
            add_hint=entry.get("add_hint") if entry.get("add_hint") is not None else sec.add_hint,
        )

    if not table_ids and not entry.get("di"):
        return None

    afn = _parse_afn(entry.get("afn"))
    if afn is None and entry.get("di"):
        afn, _ = resolve_afn(di=entry["di"], text=entry.get("title") or "")

    return MessageSection(
        section_id=entry.get("candidate_id") or f"di_{entry.get('di', 'unknown')}",
        title=entry.get("title") or entry.get("di") or "",
        afn=afn,
        di=entry.get("di") or "",
        description=entry.get("description") or entry.get("title") or "",
        table_ids=table_ids,
        dir_hint=entry.get("dir_hint"),
        add_hint=entry.get("add_hint"),
    )


def _parse_afn(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("0X"):
        return int(text, 16)
    try:
        return int(text, 16)
    except ValueError:
        return int(text, 10)


def _title_score(title: str) -> int:
    if not title:
        return 0
    score = len(title)
    if _TITLE_SKIP_RE.match(title.strip()):
        score -= 50
    if _GENERIC_TITLE_RE.match(title.strip()):
        score -= 30
    if any(kw in title for kw in ("查询", "上报", "设置", "添加", "返回", "删除", "启动")):
        score += 30
    if len(title) <= 12 and not re.search(r"[，,。；]", title):
        score += 10
    if re.search(r"配置.*间隔|详见|如下|所示", title):
        score -= 20
    return score


def _should_replace(existing: DiCandidate, record: DiCandidate) -> bool:
    origin_rank = {"table_row": 4, "table_title": 3, "section": 2, "paragraph": 1, "unknown": 0}
    if origin_rank.get(record.origin, 0) > origin_rank.get(existing.origin, 0):
        if not _is_weak_title(record.title) or origin_rank.get(record.origin, 0) >= 3:
            return True
    if existing.origin == "table_row" and not _is_weak_title(existing.title):
        return False
    if _is_weak_title(existing.title) and not _is_weak_title(record.title):
        return True
    if record.table_id and record.row_index is not None and _is_weak_title(existing.title):
        return True
    return _title_score(record.title) > _title_score(existing.title)


def _is_weak_title(title: str) -> bool:
    t = title.strip()
    if not t:
        return True
    if _TITLE_SKIP_RE.match(t):
        return True
    if "应用功能码" in t or "应用功能表" in t:
        return True
    return False


def _title_from_table(title: str | None) -> str:
    if not title:
        return ""
    return title.strip()


def _section_title(sec: MessageSection) -> str:
    title = sec.title.strip()
    if not _is_weak_title(title):
        return title
    return sec.description.strip() or title


def _clean_di_from_title(title: str) -> str:
    cleaned = extract_di_from_text(title).di or ""
    if cleaned:
        return re.sub(re.escape(cleaned), "", title, flags=re.I)
    cleaned = re.sub(r"E8(?:\s+[0-9A-Fa-f]{2}){3}", "", title, flags=re.I).strip(" ，,。:：")
    return cleaned.strip()


def _link_sections(doc: DocumentIR, candidates: list[DiCandidate]) -> None:
    di_to_section: dict[str, str] = {}
    for sec in doc.sections:
        if sec.di:
            di_to_section[sec.di.upper()] = sec.section_id

    for cand in candidates:
        if cand.section_id:
            continue
        sec_id = di_to_section.get(cand.di)
        if sec_id:
            cand.section_id = sec_id
            continue
        if cand.table_id:
            for sec in doc.sections:
                if cand.table_id in sec.table_ids:
                    cand.section_id = sec.section_id
                    break


def _link_field_tables(doc: DocumentIR, candidates: list[DiCandidate]) -> None:
    for cand in candidates:
        for table in doc.tables:
            if table.id == cand.table_id and cand.origin == "table_row":
                continue
            if not is_payload_field_table(table):
                continue
            if _table_matches_candidate(cand, table):
                if table.id not in cand.field_table_ids:
                    cand.field_table_ids.append(table.id)


def _table_matches_candidate(cand: DiCandidate, table) -> bool:
    title = table.title or ""
    if _di_in_text(title, cand.di):
        return _table_dir_matches(cand, title)
    ct = _normalize_match_text(cand.title)
    tt = _normalize_match_text(title)
    if len(ct) >= 4 and (ct in tt or tt in ct):
        return _table_dir_matches(cand, title)
    for kw in _title_keywords(cand.title):
        if kw in title:
            return _table_dir_matches(cand, title)
    return False


def _table_dir_matches(cand: DiCandidate, table_title: str) -> bool:
    if cand.dir_hint is None:
        return True
    table_dir = infer_dir_from_text(table_title)
    if table_dir is None:
        return True
    return table_dir == cand.dir_hint


def _di_in_text(text: str, di: str) -> bool:
    if not text or not di:
        return False
    compact = di.upper().replace(" ", "")
    text_upper = text.upper().replace(" ", "")
    if compact in text_upper:
        return True
    spaced = " ".join(compact[i:i + 2] for i in range(0, len(compact), 2))
    return spaced.upper() in text.upper()


def _normalize_match_text(text: str) -> str:
    cleaned = re.sub(r"E8(?:\s+[0-9A-Fa-f]{2}){3}", "", text, flags=re.I)
    cleaned = re.sub(r"[：:，,。()（）\s]", "", cleaned)
    for prefix in ("返回", "查询", "上报", "设置", "添加", "删除"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.strip()


def _title_keywords(title: str) -> list[str]:
    t = re.sub(r"^(返回|查询|上报|设置|添加|删除|启动)", "", title.strip())
    t = re.sub(r"[（(].*?[)）]", "", t)
    t = t.strip()
    if len(t) < 3:
        return []
    return [t] if len(t) >= 4 else []


def _di_headers(table) -> list[str]:
    if table.rows and _is_di_header_row(table.rows[0]):
        return table.rows[0]
    if table.headers and _is_di_header_row(table.headers):
        return table.headers
    return table.headers or []


def _is_di_header_row(row: list[str]) -> bool:
    if not row:
        return False
    first = row[0].strip().upper()
    return first in {"DI3", "DI2", "DI0", "DI"} or first == "数据标识编码"
