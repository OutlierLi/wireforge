"""Tests for DI-centric document catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docx")

from doc_parser.chunk_messages import apply_sections
from doc_parser.di_catalog import build_di_catalog
from doc_parser.parse_docx import parse_docx
from protocol_extend.document_pipeline import build_document_catalog, catalog_scan_summary

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csg_multi_message.docx"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalog():
    if not FIXTURE.exists():
        from tests.fixtures.build_multi_message_docx import build_multi_message_docx
        build_multi_message_docx(FIXTURE)
    doc = apply_sections(parse_docx(FIXTURE, root=ROOT))
    return build_document_catalog(doc)


def test_catalog_has_di_with_titles(catalog):
    assert len(catalog) >= 2
    ready = [c for c in catalog if c.get("ready_to_extend")]
    assert len(ready) >= 2
    dis = {c["di"] for c in ready}
    assert "E8030304" in dis
    assert "E8030306" in dis
    for entry in ready:
        assert entry.get("title")
        assert entry.get("candidate_id")


def test_catalog_infers_afn_from_di(catalog):
    for entry in catalog:
        if entry.get("di"):
            assert entry.get("afn") is not None
            assert entry.get("afn_source") in {"di_derived", "explicit", "semantic", "section", "table_title", None}


def test_scan_summary(catalog):
    s = catalog_scan_summary(catalog)
    assert s["total"] >= 2
    assert s["ready"] >= 2
    assert s["missing_di"] == 0
