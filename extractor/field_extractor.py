"""Extract FieldCandidate dicts from DocumentIR tables."""

from __future__ import annotations

import re
from typing import Any

from doc_parser.document_ir import TableNode
from doc_parser.metadata_extractor import extract_from_table_rows, normalize_di_token
from doc_parser.normalize_table import (
    column_index,
    is_field_table,
    is_meta_table,
    resolve_table_layout,
)
from extractor.enum_extractor import build_evidence_from_desc

_LENGTH_RE = re.compile(r"(\d+)\s*字?节?", re.I)
_AFN_FUNC_CELL = re.compile(r"^\d{2}[Hh]$")
_SKIP_FIELD_NAMES = frozenset({"字段", "名称", "数据项", "数据内容", "读参数", "写参数"})


def normalize_field_name(raw: str) -> str:
    name = raw.strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^\w\u4e00-\u9fff]", "", name)
    if not name:
        return "field"
    if name[0].isdigit():
        return f"f_{name}"
    return name.lower() if name.isascii() else name


def parse_length(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    m = _LENGTH_RE.search(text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    return None


def is_app_function_table(table: TableNode) -> bool:
    title = (table.title or "").lower()
    if "应用功能" in title:
        return True
    for row in table.rows[:4]:
        if not row:
            continue
        if _AFN_FUNC_CELL.match((row[0] or "").strip()):
            if any(normalize_di_token(cell) for cell in row):
                return True
    return False


def is_payload_field_table(table: TableNode) -> bool:
    if is_app_function_table(table):
        return False
    headers, rows = resolve_table_layout(table.headers, table.rows)
    if is_meta_table(headers):
        return False
    if is_field_table(headers) and rows:
        return True
    title = table.title or ""
    if rows and len(rows[0]) >= 2:
        if any(k in title for k in ("数据标识内容", "数据单元", "报文内容", "内容格式")):
            return True
    return False


def extract_fields_from_table(table: TableNode) -> list[dict[str, Any]]:
    if is_app_function_table(table):
        return []

    headers, rows = resolve_table_layout(table.headers, table.rows)
    if not is_field_table(headers):
        return []

    name_col = column_index(headers, "字段") or 0
    len_col = column_index(headers, "长度")
    desc_col = column_index(headers, "说明")
    fmt_col = column_index(headers, "格式")

    fields: list[dict[str, Any]] = []
    for row_idx, row in enumerate(rows):
        if len(row) <= name_col or not row[name_col].strip():
            continue
        name_raw = row[name_col].strip()
        if name_raw in _SKIP_FIELD_NAMES:
            continue
        if _AFN_FUNC_CELL.match(name_raw):
            continue
        if normalize_di_token(name_raw):
            continue

        length_text = row[len_col].strip() if len_col is not None and len_col < len(row) else None
        fmt_text = row[fmt_col].strip() if fmt_col is not None and fmt_col < len(row) else None
        desc = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else name_raw
        if fmt_text and fmt_text not in desc:
            desc = f"{desc} ({fmt_text})" if desc else fmt_text
        if not desc and len(row) > name_col + 1:
            desc = " ".join(row[name_col + 1 :])

        evidence = build_evidence_from_desc(desc)
        if fmt_text and fmt_text.upper() in {"BIN", "BCD", "BS"}:
            evidence.append(f"format:{fmt_text.upper()}")

        field: dict[str, Any] = {
            "name": normalize_field_name(name_raw),
            "desc": desc or name_raw,
            "evidence": evidence,
            "provenance": {
                "table_id": table.id,
                "row_index": row_idx,
                "raw_row": row,
            },
        }
        byte_len = parse_length(length_text)
        if byte_len is not None:
            field["bytes"] = byte_len
        fields.append(field)

    return fields


def extract_meta_from_table(table: TableNode) -> dict[str, Any]:
    """Extract AFN/DI/dir hints from metadata tables."""
    hints = extract_from_table_rows(table.rows, headers=table.headers)
    meta: dict[str, Any] = {}
    if hints.afn is not None:
        meta["afn"] = hints.afn
    if hints.di:
        meta["di"] = hints.di
    if hints.dir_hint is not None:
        meta["dir"] = hints.dir_hint
    if hints.add_hint is not None:
        meta["add"] = hints.add_hint
    return meta


def classify_table(table: TableNode) -> str:
    if is_app_function_table(table):
        return "app_function"
    if is_meta_table(table.headers):
        return "meta"
    if is_payload_field_table(table):
        return "field"
    headers, _ = resolve_table_layout(table.headers, table.rows)
    if is_field_table(headers):
        return "field"
    return "unknown"
