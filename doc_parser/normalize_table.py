"""Table normalization — headers, field-table detection, title association."""

from __future__ import annotations

import re
from typing import Any

_FIELD_HEADER_KEYS = ("字段", "名称", "数据项", "参数", "数据内容", "name", "field")
_FORMAT_HEADER_KEYS = ("数据格式", "格式", "format", "type")
_LENGTH_HEADER_KEYS = ("长度", "字节", "字节数", "byte", "length", "size")
_DESC_HEADER_KEYS = ("说明", "描述", "含义", "备注", "desc", "description", "单位")

_META_HEADER_KEYS = ("afn", "di", "数据标识", "功能码", "报文")


def normalize_rows(raw_rows: list[list[str]]) -> list[list[str]]:
    """Strip cells and drop fully empty rows."""
    out: list[list[str]] = []
    for row in raw_rows:
        cells = [c.strip() for c in row]
        if any(cells):
            out.append(cells)
    return out


def _row_looks_like_field_header(row: list[str]) -> bool:
    blob = " ".join(row).lower()
    if any(k in blob for k in _FIELD_HEADER_KEYS):
        return True
    if "数据内容" in blob and ("字节" in blob or "格式" in blob):
        return True
    return False


def detect_header_row(rows: list[list[str]]) -> int | None:
    """Return index of header row, or None if no field-table header found."""
    for idx, row in enumerate(rows[:3]):
        if _row_looks_like_field_header(row):
            return idx
    return None


def is_field_table(headers: list[str]) -> bool:
    blob = " ".join(headers).lower()
    if any(k in blob for k in _FIELD_HEADER_KEYS):
        return True
    if "数据内容" in blob and ("字节" in blob or "格式" in blob):
        return True
    return False


def is_meta_table(headers: list[str]) -> bool:
    blob = " ".join(headers).lower()
    return any(k in blob for k in _META_HEADER_KEYS) and not is_field_table(headers)


def normalize_headers(headers: list[str]) -> list[str]:
    normalized: list[str] = []
    for h in headers:
        h_lower = h.lower().strip()
        if any(k in h_lower for k in _FIELD_HEADER_KEYS) or "数据内容" in h:
            normalized.append("字段")
        elif any(k in h_lower for k in _LENGTH_HEADER_KEYS) or h in ("字节数",):
            normalized.append("长度")
        elif any(k in h_lower for k in _FORMAT_HEADER_KEYS):
            normalized.append("格式")
        elif any(k in h_lower for k in _DESC_HEADER_KEYS):
            normalized.append("说明")
        else:
            normalized.append(h.strip())
    return normalized


def column_index(headers: list[str], canonical: str) -> int | None:
    aliases = {
        "字段": _FIELD_HEADER_KEYS + ("数据内容",),
        "长度": _LENGTH_HEADER_KEYS + ("字节数",),
        "说明": _DESC_HEADER_KEYS + _FORMAT_HEADER_KEYS,
        "格式": _FORMAT_HEADER_KEYS,
    }
    keys = aliases.get(canonical, (canonical,))
    for idx, h in enumerate(headers):
        h_lower = h.lower()
        if h == canonical or any(k in h_lower for k in keys) or (canonical == "字段" and h == "字段"):
            return idx
    return None


def resolve_table_layout(
    headers: list[str],
    rows: list[list[str]],
) -> tuple[list[str], list[list[str]]]:
    """Return effective headers and body rows (handles header embedded in rows)."""
    if is_field_table(headers):
        return headers, rows
    if rows and _row_looks_like_field_header(rows[0]):
        return normalize_headers(rows[0]), rows[1:]
    return headers, rows


def find_title_for_table(
    paragraphs: list[Any],
    table_index: int,
    *,
    table_order_in_doc: int,
) -> str | None:
    """Find nearest heading or protocol-related paragraph before this table."""
    best: str | None = None
    for para in paragraphs:
        text = getattr(para, "text", "") or ""
        style = getattr(para, "style", None)
        style_name = getattr(style, "name", None) if style else None
        if not text.strip():
            continue
        if style_name and re.match(r"Heading\s*[1-3]", style_name, re.I):
            best = text.strip()
        elif any(kw in text for kw in ("数据单元", "报文", "DI", "AFN", "功能")):
            best = text.strip()
    return best


def parse_table_structure(rows: list[list[str]]) -> dict[str, Any]:
    """Split raw rows into headers + body rows."""
    rows = normalize_rows(rows)
    if not rows:
        return {"headers": [], "rows": []}

    header_idx = detect_header_row(rows)
    if header_idx is not None:
        headers = normalize_headers(rows[header_idx])
        body = rows[header_idx + 1 :]
        return {"headers": headers, "rows": body}

    return {"headers": [], "rows": rows}
