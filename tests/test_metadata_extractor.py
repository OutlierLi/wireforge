"""Tests for metadata_extractor — AFN/DI/KV/DI derivation."""

from __future__ import annotations

from doc_parser.metadata_extractor import (
    derive_afn_from_di,
    extract_di_from_row,
    extract_di_from_text,
    extract_from_kv_row,
    extract_from_table_rows,
    infer_afn_from_semantics,
    merge_di_parts,
    normalize_di_token,
    resolve_afn,
)


def test_derive_afn_from_di():
    assert derive_afn_from_di("E80505A0") == 5
    assert derive_afn_from_di("E80304FF") == 3


def test_normalize_di_spaced():
    assert normalize_di_token("E8 05 05 A0") == "E80505A0"
    assert normalize_di_token("E80505A0") == "E80505A0"


def test_merge_di_parts_split_columns():
    assert merge_di_parts("E8", "05", "05", "A0") == "E80505A0"


def test_extract_di_from_split_row():
    row = ["E8", "05", "05", "A0", "查询测试节点信息", "备注", "下行"]
    parsed = extract_di_from_row(row, headers=["DI3", "DI2", "DI1", "DI0", "名称及说明", "备注", "传输方向"])
    assert parsed is not None
    assert parsed.di == "E80505A0"
    assert "查询" in parsed.title


def test_extract_di_from_app_function_row():
    row = ["03H", "读参数", "E8 05 05 A1", "返回测试节点信息", "0", "新增"]
    parsed = extract_di_from_row(row)
    assert parsed is not None
    assert parsed.di == "E80505A1"
    assert parsed.title == "返回测试节点信息"


def test_infer_afn_from_semantics():
    assert infer_afn_from_semantics("上报节点状态") == 5
    assert infer_afn_from_semantics("查询测试信息") == 3
    assert infer_afn_from_semantics("设置测试参数") == 2


def test_resolve_afn_from_di():
    afn, source = resolve_afn(di="E80505A0", text="查询测试节点")
    assert afn == 5
    assert source == "di_derived"


def test_extract_afn_function_code_cn():
    h = extract_di_from_text("功能码：05")
    assert h.afn == 5


def test_extract_di_bare_e8():
    h = extract_di_from_text("数据标识 E80505A0")
    assert h.di == "E80505A0"
    assert h.afn == 5


def test_kv_table_meta():
    rows = [["功能码", "05"], ["数据标识", "E80505A0"]]
    h = extract_from_table_rows(rows)
    assert h.afn == 5
    assert h.di == "E80505A0"
    assert h.confidence == "high"


def test_kv_row_di_only_derives_afn():
    h = extract_from_kv_row("数据标识", "E80505A1")
    assert h.di == "E80505A1"
    assert h.afn == 5
