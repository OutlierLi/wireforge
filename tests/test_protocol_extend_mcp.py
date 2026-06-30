"""Integration tests for protocol_extend_run MCP (DOCX auto pipeline)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.map_verify import verify_route_handle
from protocol_extend.fields import field_to_yaml
from protocol_extend.schema import ExtensionSpec
from protocol_extend.validator import find_conflicts
from protocol_extend.run_log import ExtendRunLog
from mcp_servers.extend.server import call_tool, handle_message, serve

from tests.base_protocol_csg import (
    DI_ADD_SLAVE,
    DI_QUERY_DELAY,
    DI_QUERY_MODE,
    DI_QUERY_VENDOR,
)

ROOT = Path(__file__).resolve().parent.parent

HEX_EXISTING_DI = DI_QUERY_VENDOR
HEX_NEW_DI = DI_QUERY_DELAY
HEX_NEW_DI_EVIDENCE = DI_QUERY_MODE


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


def _run_docx(raw: str, doc_path: Path, **user_input) -> dict:
    rel = str(doc_path.relative_to(ROOT))
    payload = {"document_path": rel, **user_input}
    return run_protocol_extend(raw, user_input=payload)


DOCX_FIXTURE = ROOT / "tests" / "fixtures" / "csg_sample.docx"
DOCX_DI = DI_QUERY_MODE
MULTI_DOCX = ROOT / "tests" / "fixtures" / "csg_multi_message.docx"


@pytest.fixture
def docx_fixture():
    pytest.importorskip("docx")
    from tests.fixtures.build_sample_docx import build_sample_docx
    build_sample_docx(DOCX_FIXTURE)
    return DOCX_FIXTURE


@pytest.fixture
def multi_docx_fixture():
    pytest.importorskip("docx")
    from tests.fixtures.build_multi_message_docx import build_multi_message_docx
    build_multi_message_docx(MULTI_DOCX)
    return MULTI_DOCX


def test_extend_requires_document_path():
    result = run_protocol_extend("扩展 CSG 报文")
    assert result["state"] == "FAILED"
    assert "document_path" in result["error"]


def test_extend_run_log_stages(docx_fixture, ext_dir_isolated):
    result = _run_docx("从 DOCX 扩展", docx_fixture)
    assert result["state"] == "SUCCEEDED"
    log_dir = Path(result["log_dir"])
    assert (log_dir / "extend.log").exists()
    assert (log_dir / "extracted_drafts.json").exists()
    stages = list((log_dir / "stages").glob("*.json"))
    stage_names = {p.name for p in stages}
    assert any("document_parse" in n for n in stage_names)
    assert any("document_extract" in n for n in stage_names)
    assert any("inference" in n for n in stage_names)
    assert any("yaml_preview" in n for n in stage_names)
    assert any("fidelity" in n for n in stage_names)
    assert any("draft_result" in n for n in stage_names)


def test_extend_from_docx_auto_flow(ext_dir_isolated, docx_fixture):
    result = _run_docx("从 DOCX 扩展 CSG 报文", docx_fixture)
    assert result["state"] == "SUCCEEDED"
    assert result.get("batch_summary")
    assert result["batch_summary"]["accepted"] >= 1
    written = list(ext_dir_isolated.glob(f"03_{DOCX_DI}.yaml"))
    assert written
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    field = doc["variants"][0]["body"]["fields"][0]
    assert field["type"] in ("enum", "bool")
    assert "路由模式" in str(field.get("values", {}))


def test_extend_from_docx_multi_message_batch(ext_dir_isolated, multi_docx_fixture):
    result = _run_docx("从多报文 DOCX 批量扩展", multi_docx_fixture)
    assert result["state"] == "SUCCEEDED"
    summary = result["batch_summary"]
    assert summary["total"] >= 2
    assert summary["accepted"] >= 1
    written = list(ext_dir_isolated.glob("03_*.yaml"))
    assert written


def test_find_conflicts_existing():
    spec = ExtensionSpec(
        afn=0x03,
        di=HEX_EXISTING_DI,
        description="x",
        dir=0,
        add=False,
    )
    assert find_conflicts(spec)


def test_extend_array_struct_fields_to_yaml():
    fields = [
        {"name": "slave_count", "type": "uint8", "desc": "从节点数量"},
        {
            "name": "slave_addrs",
            "type": "array",
            "count_ref": "slave_count",
            "item_type": "bcd",
            "item_name": "slave_addr",
            "desc": "从节点地址列表",
            "item_fields": [
                {"name": "address", "type": "bcd", "length": 6, "byte_order": "little", "desc": "地址"},
            ],
        },
    ]
    yaml_fields = [field_to_yaml(f) for f in fields]
    assert yaml_fields[1]["type"] == "array"
    assert yaml_fields[1]["count_ref"] == "slave_count"

    spec = ExtensionSpec(
        afn=0x04,
        di=DI_ADD_SLAVE,
        description="添加从节点",
        dir=0,
        add=False,
        fields=fields,
    )
    preview = yaml_writer.render_extension_yaml(spec, "test")
    assert "count_ref: slave_count" in preview


def test_extend_router_id_beyond_builtin():
    spec = ExtensionSpec(afn=0x08, di="E8080001", description="x", dir=0, add=False)
    assert spec.router_id() == "afn08_di_router"


def test_extend_run_log_class(tmp_path):
    log = ExtendRunLog(tmp_path / "run1")
    log.log_stage("test", {"summary": "hello", "value": 1})
    assert log.log_path.exists()
    assert list(log.stages_dir.glob("*.json"))


def test_mcp_tool_call_docx(docx_fixture, ext_dir_isolated):
    result = call_tool("protocol_extend_run", {
        "raw_input": "扩展",
        "user_input": {"document_path": str(DOCX_FIXTURE.relative_to(ROOT))},
    })
    assert result["state"] == "SUCCEEDED"


def test_mcp_stdio_json_lines(docx_fixture):
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "protocol_extend_run",
            "arguments": {
                "raw_input": "扩展",
                "user_input": {"document_path": str(DOCX_FIXTURE.relative_to(ROOT))},
            },
        },
    }
    raw = json.dumps(request).encode("utf-8") + b"\n"
    output = io.BytesIO()
    code = serve(io.BytesIO(raw), output)
    assert code == 0
    response = json.loads(output.getvalue().decode("utf-8"))
    text = response["result"]["content"][0]["text"]
    assert "SUCCEEDED" in text or "FAILED" in text
