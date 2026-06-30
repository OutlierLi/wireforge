"""Integration tests for protocol_extend_run MCP (C struct pipeline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.schema import ExtensionSpec
from protocol_extend.validator import find_conflicts

from tests.base_protocol_csg import DI_QUERY_VENDOR

ROOT = Path(__file__).resolve().parent.parent
C_STRUCT_DIR = ROOT / "tests" / "fixtures" / "c_struct"


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def ext_dir_isolated(ext_dir, monkeypatch):
    no_conflict = lambda spec, variants_dir=None: []
    monkeypatch.setattr("protocol_extend.validator.find_conflicts", no_conflict)
    monkeypatch.setattr("protocol_extend.state_machine.find_conflicts", no_conflict)
    return ext_dir


def test_extend_requires_c_struct_input():
    result = run_protocol_extend("扩展 CSG 报文")
    assert result["state"] == "FAILED"
    assert "c_struct" in result["error"]


def test_find_conflicts_existing():
    spec = ExtensionSpec(
        afn=0x03,
        di=DI_QUERY_VENDOR,
        description="x",
        dir=0,
        add=False,
        fields=[{"name": "a", "type": "uint8", "desc": "a"}],
    )
    assert find_conflicts(spec)
