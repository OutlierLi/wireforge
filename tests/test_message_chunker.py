"""Tests for message chunking — multi-section documents."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docx")

from doc_parser.chunk_messages import chunk_messages
from doc_parser.parse_docx import parse_docx, extract_afn_di_from_text

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csg_sample.docx"
ROOT = Path(__file__).resolve().parent.parent


def test_chunk_messages_multiple_sections():
    doc = parse_docx(FIXTURE, root=ROOT)
    sections = chunk_messages(doc)
    assert len(sections) >= 2
    dis = {s.di for s in sections if s.di}
    assert "E8000302" in dis
    assert "E8030304" in dis


def test_extract_afn_di_from_heading():
    afn, di = extract_afn_di_from_text("AFN03 DI=E8030304 查询通信延时时长")
    assert afn == 3
    assert di == "E8030304"


def test_section_has_table_ids():
    doc = parse_docx(FIXTURE, root=ROOT)
    sections = chunk_messages(doc)
    assert any(s.table_ids for s in sections)
