"""Tests for DI catalog field-table linking."""

from __future__ import annotations

from doc_parser.di_catalog import build_di_catalog, resolve_di_candidate, section_for_candidate
from doc_parser.document_ir import DocumentIR, TableNode
from doc_parser.parse_docx import parse_docx
from doc_parser.chunk_messages import apply_sections
from extractor.message_extractor import extract_message

from pathlib import Path

import pytest

pytest.importorskip("docx")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csg_multi_message.docx"
ROOT = Path(__file__).resolve().parent.parent


def _doc_with_data_content_table() -> DocumentIR:
    doc = apply_sections(parse_docx(FIXTURE, root=ROOT))
    doc.tables.append(TableNode(
        id="t_extra",
        index=len(doc.tables),
        title="E80505A0查询测试节点信息，下行",
        headers=[],
        rows=[
            ["数据内容", "数据格式", "字节数"],
            ["节点数量n", "BIN", "1"],
        ],
        provenance={"paragraph_before": doc.paragraphs[-1].id if doc.paragraphs else None},
    ))
    return doc


def test_di_catalog_links_field_table_by_di_title():
    doc = _doc_with_data_content_table()
    catalog = build_di_catalog(doc)
    entry = resolve_di_candidate(doc, di="E80505A0")
    assert entry is not None
    assert entry.get("field_table_ids")
    sec = section_for_candidate(doc, entry)
    assert sec is not None
    draft = extract_message(doc, sec)
    assert len(draft.fields) >= 1


def test_di_catalog_infers_dir_hint():
    doc = _doc_with_data_content_table()
    entry = resolve_di_candidate(doc, di="E80505A0")
    assert entry is not None
    assert entry.get("dir_hint") == 0
