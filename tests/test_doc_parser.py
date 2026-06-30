"""Tests for doc_parser — DocumentIR and parse_docx."""

from __future__ import annotations

from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from doc_parser.chunk_messages import apply_sections
from doc_parser.document_ir import DocumentIR
from doc_parser.normalize_table import is_field_table, parse_table_structure
from doc_parser.parse_docx import parse_docx

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csg_sample.docx"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sample_doc() -> DocumentIR:
    if not FIXTURE.exists():
        from tests.fixtures.build_sample_docx import build_sample_docx
        build_sample_docx(FIXTURE)
    doc = parse_docx(FIXTURE, root=ROOT)
    return apply_sections(doc)


def test_parse_docx_paragraphs_and_tables(sample_doc):
    assert sample_doc.paragraphs
    assert len(sample_doc.tables) >= 2
    assert sample_doc.source_path.endswith("csg_sample.docx")


def test_table_headers_normalized(sample_doc):
    field_table = sample_doc.tables[0]
    assert is_field_table(field_table.headers)
    assert "字段" in field_table.headers


def test_parse_table_structure():
    rows = [["字段", "长度", "说明"], ["设备类型", "2字节", "00H：单相表"]]
    structured = parse_table_structure(rows)
    assert structured["headers"]
    assert len(structured["rows"]) == 1


def test_document_ir_roundtrip(sample_doc):
    data = sample_doc.to_dict()
    restored = DocumentIR.from_dict(data)
    assert restored.doc_id == sample_doc.doc_id
    assert len(restored.tables) == len(sample_doc.tables)


def test_summary(sample_doc):
    s = sample_doc.summary()
    assert s["paragraphs"] >= 2
    assert s["tables"] >= 2
