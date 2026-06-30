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
    assert derive_afn_from_di("E8030304") == 3
    assert derive_afn_from_di("E8040304") == 4


def test_normalize_di_spaced():
    assert normalize_di_token("E8 03 03 04") == "E8030304"
    assert normalize_di_token("E8030304") == "E8030304"


def test_merge_di_parts_split_columns():
    assert merge_di_parts("E8", "03", "03", "04") == "E8030304"


def test_extract_di_from_split_row():
    row = ["E8", "03", "03", "04", "查询通信延时时长", "备注", "下行"]
    parsed = extract_di_from_row(row, headers=["DI3", "DI2", "DI1", "DI0", "名称及说明", "备注", "传输方向"])
    assert parsed is not None
    assert parsed.di == "E8030304"
    assert "查询" in parsed.title


def test_extract_di_from_app_function_row():
    row = ["03H", "读参数", "E8 03 03 06", "返回从节点信息", "0", "新增"]
    parsed = extract_di_from_row(row)
    assert parsed is not None
    assert parsed.di == "E8030306"
    assert parsed.title == "返回从节点信息"


def test_infer_afn_from_semantics():
    assert infer_afn_from_semantics("上报路由信息") == 5
    assert infer_afn_from_semantics("查询通信延时时长") == 3
    assert infer_afn_from_semantics("添加从节点") == 2


def test_resolve_afn_from_di():
    afn, source = resolve_afn(di="E8030304", text="查询通信延时时长")
    assert afn == 3
    assert source == "di_derived"


def test_extract_afn_function_code_cn():
    h = extract_di_from_text("功能码：04")
    assert h.afn == 4


def test_extract_di_bare_e8():
    h = extract_di_from_text("数据标识 E8020402")
    assert h.di == "E8020402"
    assert h.afn == 2


def test_kv_table_meta():
    rows = [["功能码", "03"], ["数据标识", "E8030304"]]
    h = extract_from_table_rows(rows)
    assert h.afn == 3
    assert h.di == "E8030304"
    assert h.confidence == "high"


def test_kv_row_di_only_derives_afn():
    h = extract_from_kv_row("数据标识", "E8030306")
    assert h.di == "E8030306"
    assert h.afn == 3
