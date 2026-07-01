"""DL/T 645-2007 全量 protocol_extend 流程测试（C struct → YAML → 写盘 → 编译/校验）."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.c_struct.builder import build_spec_from_c_struct
from protocol_extend.c_struct.parser import parse_c_struct
from protocol_extend.c_struct.to_yaml import c_struct_to_yaml_fields
from protocol_extend.c_struct.validator import validate_c_struct
from protocol_extend.fidelity_checker import check_layout_fidelity
from protocol_extend.profiles import DLT645_PROFILE
from protocol_extend.schema import ExtensionSpec

from tests.base_protocol_dlt645 import (
    BUILTIN_COMPILE_CASES,
    DLT645_EXTEND_CASES,
    Dlt645ExtendCase,
    MESSAGE_CASES,
    REAL_COMPILE_CASES,
)

ROOT = Path(__file__).resolve().parent.parent


def _case_id(case: Dlt645ExtendCase) -> str:
    return f"func_{case.func:02X}_{case.name}"


def _user_input(case: Dlt645ExtendCase) -> dict:
    payload = {
        "protocol": "dlt645",
        "func": f"0x{case.func:02X}",
        "di": case.di,
        "description": case.description,
        "c_struct_path": str(case.c_struct_file),
    }
    if case.dir is not None:
        payload["dir"] = "downlink" if case.dir == 0 else "uplink"
    return payload


def _field_map(fields: list[dict]) -> dict[str, dict]:
    return {f["name"]: f for f in fields}


def _assert_field_checks(fields: list[dict], case: Dlt645ExtendCase) -> None:
    by_name = _field_map(fields)
    for check in case.field_checks:
        assert check.name in by_name, f"missing field {check.name!r} in {case.name}"
        assert by_name[check.name]["type"] == check.type, (
            f"{case.name}.{check.name}: expected {check.type}, got {by_name[check.name]['type']}"
        )


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    monkeypatch.setattr("protocol_extend.profiles.EXTENSIONS_DIR_OVERRIDE", tmp_path)
    yield tmp_path
    monkeypatch.setattr("protocol_extend.profiles.EXTENSIONS_DIR_OVERRIDE", None)


@pytest.fixture
def ext_dir_no_conflict(ext_dir, monkeypatch):
    no_conflict = lambda spec, variants_dir=None: []
    monkeypatch.setattr("protocol_extend.validator.find_conflicts", no_conflict)
    monkeypatch.setattr("protocol_extend.state_machine.find_conflicts", no_conflict)
    return ext_dir


@pytest.fixture
def ext_dir_real_compile(ext_dir_no_conflict, monkeypatch):
    """真实 compile 时把 tmp 扩展 YAML 注入 loader。"""
    from protocol_tool.utils.yaml_loader import load_yaml
    from protocol_tool.compiler.loader import load_protocol as original_load

    override_dir = ext_dir_no_conflict

    def load_protocol_with_test_extensions(registry_path, protocol_name, **kwargs):
        unit = original_load(registry_path, protocol_name, **kwargs)
        if unit and protocol_name == "dlt645_2007":
            for yaml_path in sorted(override_dir.glob("*.yaml")):
                data = load_yaml(yaml_path)
                if data:
                    unit.variant_data.append(data)
        return unit

    monkeypatch.setattr(
        "protocol_tool.compiler.loader.load_protocol",
        load_protocol_with_test_extensions,
    )
    return override_dir


@pytest.fixture
def ext_dir_mock_compile(ext_dir_no_conflict, monkeypatch):
    def _compile_and_verify(record, draft, draft_index, spec, written, log):
        rel = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)
        draft.status = "accepted"
        draft.extension_file = rel
        draft.last_error = ""
        log.log_draft_result(draft_index, draft, status="accepted", extra={"extension_file": rel})
        return True, True

    monkeypatch.setattr("protocol_extend.state_machine._compile_and_verify", _compile_and_verify)
    return ext_dir_no_conflict


# ── Layer 1: C struct 解析与 YAML 字段转换 ────────────────────────────────


@pytest.mark.parametrize("case", DLT645_EXTEND_CASES, ids=_case_id)
def test_c_struct_parse_validate(case: Dlt645ExtendCase):
    source = case.c_struct_file.read_text(encoding="utf-8")
    defn = parse_c_struct(source, path=str(case.c_struct_file))
    validate_c_struct(defn)
    assert defn.metadata.func == case.func
    assert defn.metadata.di.upper() == case.di.upper()


@pytest.mark.parametrize("case", DLT645_EXTEND_CASES, ids=_case_id)
def test_c_struct_to_yaml_fields(case: Dlt645ExtendCase):
    source = case.c_struct_file.read_text(encoding="utf-8")
    defn = parse_c_struct(source, path=str(case.c_struct_file))
    fields = c_struct_to_yaml_fields(defn)
    assert fields, f"{case.name} should produce fields"
    _assert_field_checks(fields, case)


@pytest.mark.parametrize("case", DLT645_EXTEND_CASES, ids=_case_id)
def test_build_spec_from_c_struct(case: Dlt645ExtendCase):
    spec = build_spec_from_c_struct(
        f"扩展645 {case.description}",
        _user_input(case),
    )
    assert spec.protocol == "dlt645_2007"
    assert spec.func == case.func
    assert spec.di.upper() == case.di.upper()
    assert spec.description == case.description
    _assert_field_checks(spec.fields, case)


@pytest.mark.parametrize("case", DLT645_EXTEND_CASES, ids=_case_id)
def test_profile_build_variants(case: Dlt645ExtendCase):
    spec = build_spec_from_c_struct(f"扩展645 {case.name}", _user_input(case))
    variants = DLT645_PROFILE.build_variants(spec)
    assert len(variants) == 1
    variant = variants[0]
    assert variant["router"] == case.router
    assert variant["match"][case.selector_field] == case.di.upper()
    body_fields = variant["body"]["fields"]
    _assert_field_checks(body_fields, case)


@pytest.mark.parametrize("case", DLT645_EXTEND_CASES, ids=_case_id)
def test_layout_fidelity(case: Dlt645ExtendCase):
    spec = build_spec_from_c_struct(f"扩展645 {case.name}", _user_input(case))
    report = check_layout_fidelity(spec)
    failed = [c["id"] for c in report.get("checks", []) if not c.get("ok")]
    assert not failed, report
    assert report.get("confidence") in ("high", "medium")


# ── Layer 2: extend_run 写 YAML（mock 编译，覆盖全部 FUNC）──────────────────


@pytest.mark.parametrize("case", MESSAGE_CASES, ids=_case_id)
def test_extend_run_all_messages(case: Dlt645ExtendCase, ext_dir_mock_compile):
    result = run_protocol_extend(
        f"扩展645 {case.description}",
        user_input=_user_input(case),
    )
    assert result["state"] == "SUCCEEDED", result.get("error")
    assert result.get("protocol") == "dlt645_2007"

    written = ext_dir_mock_compile / f"{case.func:02X}_{case.di.upper()}.yaml"
    assert written.exists(), f"missing extension file for {case.name}"

    doc = yaml.safe_load(written.read_text(encoding="utf-8"))
    variant = doc["variants"][0]
    assert variant["router"] == case.router
    assert variant["match"][case.selector_field] == case.di.upper()
    _assert_field_checks(variant["body"]["fields"], case)

    if case.builtin:
        assert result.get("template_only") is not True
    else:
        assert result.get("template_only") is True
        assert "router_hint" in result


@pytest.mark.parametrize("case", MESSAGE_CASES, ids=_case_id)
def test_extend_run_log_stages(case: Dlt645ExtendCase, ext_dir_mock_compile):
    result = run_protocol_extend(
        f"扩展645 {case.description}",
        user_input=_user_input(case),
    )
    assert result["state"] == "SUCCEEDED"
    log_dir = Path(result["log_dir"])
    stages = {p.name for p in (log_dir / "stages").glob("*.json")}
    assert any("c_struct_parse" in n for n in stages)
    assert any("yaml_preview" in n for n in stages)
    assert any("fidelity" in n for n in stages)
    assert any("draft_result" in n for n in stages)


# ── Layer 3: 内置 router 真实编译 + protocol map 校验 ───────────────────────


@pytest.mark.parametrize("case", REAL_COMPILE_CASES, ids=_case_id)
def test_extend_run_real_compile(case: Dlt645ExtendCase, ext_dir_real_compile):
    """内置 router（0x11/0x14/0x16/0x1B）走真实 compile + route 校验。"""
    result = run_protocol_extend(
        f"扩展645 真实编译 {case.description}",
        user_input=_user_input(case),
    )
    assert result["state"] == "SUCCEEDED", result.get("error")
    assert result.get("template_only") is not True
    assert result.get("compile_ok") is True
    assert result.get("map_ok") is True

    written = ext_dir_real_compile / f"{case.func:02X}_{case.di.upper()}.yaml"
    assert written.exists()

    doc = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert doc["variants"][0]["id"].startswith("dlt645_2007.ext.")
    _assert_field_checks(doc["variants"][0]["body"]["fields"], case)


def test_all_dlt645_message_funcs_covered():
    """protocol_info 中全部 FUNC 均有 extend 用例。"""
    from tests.protocol_info import DLT645_MESSAGES

    case_funcs = {c.func for c in MESSAGE_CASES}
    message_funcs = {m["func"] for m in DLT645_MESSAGES}
    missing = message_funcs - case_funcs
    assert not missing, f"missing extend cases for func: {sorted(missing)}"


def test_dlt645_extend_case_count():
    assert len(MESSAGE_CASES) >= 15
    assert len(BUILTIN_COMPILE_CASES) == 6
    assert len(REAL_COMPILE_CASES) == 4
