"""Tests for extractor — field and message extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docx")

from doc_parser.chunk_messages import apply_sections
from doc_parser.parse_docx import parse_docx
from extractor.enum_extractor import build_evidence_from_desc
from extractor.field_extractor import extract_fields_from_table, normalize_field_name, parse_length
from extractor.message_extractor import extract_message

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csg_sample.docx"
ROOT = Path(__file__).resolve().parent.parent


def test_enum_evidence_from_desc():
    lines = build_evidence_from_desc("00H：单相表；01H：三相表；02H：采集器")
    assert any("单相表" in ln for ln in lines)
    assert len(lines) >= 2


def test_parse_length():
    assert parse_length("2字节") == 2
    assert parse_length("3") == 3


def test_normalize_field_name():
    assert normalize_field_name("设备类型") == "设备类型"


def test_extract_fields_data_content_header():
    from doc_parser.document_ir import TableNode
    from extractor.field_extractor import classify_table, is_payload_field_table

    table = TableNode(
        id="tx",
        index=0,
        title="查询测试节点信息数据标识内容格式",
        headers=[],
        rows=[
            ["数据内容", "数据格式", "字节数"],
            ["从节点起始序号", "BIN", "2"],
            ["从节点数量", "BIN", "1"],
        ],
    )
    assert is_payload_field_table(table)
    assert classify_table(table) == "field"
    fields = extract_fields_from_table(table)
    assert len(fields) == 2
    assert fields[0]["bytes"] == 2
    assert "BIN" in fields[0]["desc"]


def test_app_function_table_not_field():
    from doc_parser.document_ir import TableNode
    from extractor.field_extractor import classify_table, extract_fields_from_table

    table = TableNode(
        id="ty",
        index=1,
        title="表格 7 应用功能码格式",
        headers=[],
        rows=[["03H", "读参数", "E8 05 05 A0", "返回测试", "0", "新增"]],
    )
    assert classify_table(table) == "app_function"
    assert extract_fields_from_table(table) == []


def test_extract_fields_from_table():
    doc = apply_sections(parse_docx(FIXTURE, root=ROOT))
    table = doc.tables[0]
    fields = extract_fields_from_table(table)
    assert fields
    assert fields[0]["name"] == "设备类型"
    assert fields[0].get("bytes") == 2
    assert fields[0]["evidence"]


def test_extract_message_device_type_enum():
    doc = apply_sections(parse_docx(FIXTURE, root=ROOT))
    section = next(s for s in doc.sections if s.di == "E80304F5")
    draft = extract_message(doc, section)
    assert draft.di == "E80304F5"
    assert draft.afn == 3
    assert draft.fields
    assert draft.fields[0]["name"] == "设备类型"


def test_type_inferencer_enum_from_extracted_fields():
    from protocol_extend.fields import process_agent_fields

    doc = apply_sections(parse_docx(FIXTURE, root=ROOT))
    section = next(s for s in doc.sections if s.di == "E80304F5")
    draft = extract_message(doc, section)
    _, report, _ = process_agent_fields(draft.fields)
    assert report[0]["semantic_type"] == "enum"
