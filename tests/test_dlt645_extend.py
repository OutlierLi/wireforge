"""DL/T 645-2007 protocol extend pipeline tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.parser import build_spec
from protocol_extend.profiles import detect_protocol, DLT645_PROFILE
from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent
TEST_DI = "00099999"


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    monkeypatch.setattr("protocol_extend.profiles.EXTENSIONS_DIR_OVERRIDE", tmp_path)
    yield tmp_path
    monkeypatch.setattr("protocol_extend.profiles.EXTENSIONS_DIR_OVERRIDE", None)


@pytest.fixture
def ext_dir_isolated(ext_dir, monkeypatch):
    no_conflict = lambda spec, variants_dir=None: []
    monkeypatch.setattr("protocol_extend.validator.find_conflicts", no_conflict)
    monkeypatch.setattr("protocol_extend.state_machine.find_conflicts", no_conflict)

    def _compile_and_verify(record, draft, draft_index, spec, written, log):
        rel = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)
        draft.status = "accepted"
        draft.extension_file = rel
        draft.last_error = ""
        log.log_draft_result(draft_index, draft, status="accepted", extra={"extension_file": rel})
        return True, True

    monkeypatch.setattr("protocol_extend.state_machine._compile_and_verify", _compile_and_verify)
    return ext_dir


def test_detect_protocol_from_text():
    assert detect_protocol("扩展 DLT645 读数据 DI 00099999", {}) == "dlt645_2007"
    assert detect_protocol("扩展 CSG 报文 AFN03 DI E8039999", {}) == "csg_2016"
    assert detect_protocol("", {"protocol": "dlt645"}) == "dlt645_2007"
    assert detect_protocol("", {"di": "00010000"}) == "dlt645_2007"
    assert detect_protocol("", {"di": "E8030306"}) == "csg_2016"


def test_dlt645_build_variants():
    spec = ExtensionSpec(
        protocol="dlt645_2007",
        func=0x11,
        di=TEST_DI,
        description="自定义电能量",
        dir=1,
        fields=[{"name": "energy", "type": "uint32", "desc": "电能量"}],
    )
    variants = DLT645_PROFILE.build_variants(spec)
    assert len(variants) == 1
    assert variants[0]["router"] == "read_data_response_di"
    assert variants[0]["match"]["di"] == TEST_DI
    assert variants[0]["id"].startswith("dlt645_2007.ext.")


def test_dlt645_build_variants_write_data():
    spec = ExtensionSpec(
        protocol="dlt645_2007",
        func=0x14,
        di=TEST_DI,
        description="写数据扩展",
        fields=[{"name": "value", "type": "uint16", "desc": "写入值"}],
    )
    variants = DLT645_PROFILE.build_variants(spec)
    assert variants[0]["router"] == "write_data_request_di"
    assert variants[0]["match"]["di"] == TEST_DI
    assert variants[0]["id"].endswith("_req")


def test_dlt645_build_variants_freeze():
    spec = ExtensionSpec(
        protocol="dlt645_2007",
        func=0x16,
        di="00010000",
        description="自定义冻结",
        fields=[{"name": "freeze_time", "type": "datetime_ymdhm", "desc": "冻结时间"}],
    )
    variants = DLT645_PROFILE.build_variants(spec)
    assert variants[0]["router"] == "freeze_request_di"
    assert variants[0]["match"]["freeze_type"] == "00010000"
    assert "di" not in variants[0]["match"]
    assert spec.dir == 0


def test_dlt645_template_only_unknown_func():
    spec = ExtensionSpec(protocol="dlt645_2007", func=0x17, di=TEST_DI, description="改速率扩展")
    DLT645_PROFILE.apply_defaults(spec)
    assert not DLT645_PROFILE.has_builtin_router(spec)
    variants = DLT645_PROFILE.build_variants(spec)
    assert variants[0]["router"] == "change_baudrate_request_body"


def test_dlt645_extension_filename():
    spec = ExtensionSpec(protocol="dlt645_2007", func=0x11, di=TEST_DI, description="x", dir=1)
    assert DLT645_PROFILE.extension_filename(spec) == f"11_{TEST_DI}.yaml"


def test_dlt645_extend_run(ext_dir_isolated):
    result = run_protocol_extend(
        "扩展 DLT645 读数据应答 DI",
        user_input={
            "protocol": "dlt645",
            "func": "0x11",
            "di": TEST_DI,
            "description": "自定义扩展电能量",
            "fields": [
                {
                    "name": "rate_index",
                    "type": "uint8",
                    "desc": "rate index",
                    "evidence": ["0x00: total", "0x01: rate 1"],
                },
                {"name": "energy_raw", "type": "uint32_le", "desc": "raw energy"},
            ],
        },
    )
    assert result["state"] == "SUCCEEDED"
    assert result.get("protocol") == "dlt645_2007"
    written = ext_dir_isolated / f"11_{TEST_DI}.yaml"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert "read_data_response_di" in text
    assert TEST_DI in text


def test_build_spec_auto_detect_645():
    spec = build_spec("扩展645读数据 DI 00088888", {"fields": [{"name": "x", "type": "uint8", "desc": "x"}]})
    assert spec.protocol == "dlt645_2007"
    assert spec.di == "00088888"
