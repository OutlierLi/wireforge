"""Tests for C struct protocol extension pipeline."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.c_struct.parser import parse_c_struct
from protocol_extend.c_struct.to_yaml import c_struct_to_yaml_fields
from protocol_extend.c_struct.validator import validate_c_struct
from protocol_extend.c_struct.builder import build_spec_from_c_struct
from protocol_extend.schema import ExtensionSpec
from protocol_extend.validator import find_conflicts
from protocol_extend.run_log import ExtendRunLog
from mcp_servers.extend.server import call_tool, serve

from tests.base_protocol_csg import DI_ADD_SLAVE, DI_QUERY_VENDOR

ROOT = Path(__file__).resolve().parent.parent
C_STRUCT_DIR = ROOT / "tests" / "fixtures" / "c_struct"

TEST_DI = "E8039999"
TEST_DI_ENUM = "E8039998"
TEST_DI_NESTED = "E8039997"


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    return tmp_path


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
        log.log_draft_result(
            draft_index, draft, status="accepted",
            extra={"extension_file": rel},
        )
        return True, True

    monkeypatch.setattr("protocol_extend.state_machine._compile_and_verify", _compile_and_verify)
    return ext_dir


def _run_c_struct(raw: str, **user_input) -> dict:
    return run_protocol_extend(raw, user_input=user_input)


def test_parse_enum_struct():
    source = (C_STRUCT_DIR / "device_type_enum.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    validate_c_struct(defn)
    fields = c_struct_to_yaml_fields(defn)
    assert fields[0]["type"] == "enum"
    assert len(fields[0]["values"]) >= 2
    assert "0x00" in fields[0]["values"]


def test_parse_nested_struct():
    source = (C_STRUCT_DIR / "nested_date.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    fields = c_struct_to_yaml_fields(defn)
    assert fields[0]["type"] == "struct"
    assert len(fields[0]["fields"]) == 3


def test_parse_flexible_array():
    source = (C_STRUCT_DIR / "query_slave_info_resp.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    fields = c_struct_to_yaml_fields(defn)
    arr = fields[2]
    assert arr["type"] == "array"
    assert arr["count_ref"] == "response_slave_count"
    assert arr["item_type"] == "node_address"


def test_parse_struct_flex_array():
    source = (C_STRUCT_DIR / "report_unrecognized_node.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    validate_c_struct(defn)
    fields = c_struct_to_yaml_fields(defn)
    assert fields[0]["name"] == "node_count"
    arr = fields[1]
    assert arr["type"] == "array"
    assert arr["count_ref"] == "node_count"
    assert arr["item_name"] == "node_info"
    assert arr["item_type"] == "struct"
    item_fields = arr["item_params"]["fields"]
    assert item_fields[0]["type"] == "node_address"
    assert item_fields[1]["type"] == "uint8"


def test_parse_geo_info_struct_flex_array():
    source = (C_STRUCT_DIR / "query_geo_info_resp.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    fields = c_struct_to_yaml_fields(defn)
    arr = fields[1]
    assert arr["item_type"] == "struct"
    geo = arr["item_params"]["fields"]
    assert geo[1] == {"name": "longitude", "type": "bcd", "length": 4, "desc": "经度(XXXX.XXXX BCD)"}
    assert geo[2]["length"] == 4
    assert geo[3]["length"] == 3


def test_parse_bcd_datetime_domain():
    source = (C_STRUCT_DIR / "set_cco_time.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    fields = c_struct_to_yaml_fields(defn)
    assert fields[0] == {
        "name": "datetime",
        "type": "bcd_datetime",
        "desc": "CCO时钟 (ssmmhhDDMMYY)",
    }


def test_parse_nested_bcd_clock_collapses_to_bcd_fields():
    source = (C_STRUCT_DIR / "nested_bcd_clock.h").read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    fields = c_struct_to_yaml_fields(defn)
    clock = fields[0]["fields"]
    assert len(clock) == 6
    assert clock[0] == {"name": "second", "type": "bcd", "length": 1, "desc": "秒"}
    assert clock[5]["name"] == "year"


def test_build_spec_pair():
    spec = build_spec_from_c_struct(
        "扩展",
        {
            "afn": "03",
            "di": TEST_DI,
            "pair": True,
            "description": "查询从节点信息",
            "c_struct_path": str(C_STRUCT_DIR / "query_slave_info_req.h"),
            "resp_c_struct_path": str(C_STRUCT_DIR / "query_slave_info_resp.h"),
        },
    )
    assert spec.pair
    assert len(spec.fields) == 2
    assert len(spec.resp_fields) == 3


def test_extend_requires_c_struct():
    result = run_protocol_extend("扩展 CSG 报文", user_input={"afn": "03", "di": TEST_DI})
    assert result["state"] == "FAILED"
    assert "c_struct" in result["error"] or "empty_payload" in result["error"]


def test_build_spec_empty_payload():
    spec = build_spec_from_c_struct(
        "查厂商",
        {
            "afn": "00",
            "di": "E8000301",
            "dir": "downlink",
            "description": "查询厂商代码",
            "empty_payload": True,
        },
    )
    assert spec.fields == []


def test_extend_empty_payload(ext_dir_isolated):
    result = _run_c_struct(
        "查厂商",
        afn="00",
        di="E8000399",
        dir="downlink",
        description="空 payload 查询示例",
        empty_payload=True,
    )
    assert result["state"] == "SUCCEEDED"
    written = list(ext_dir_isolated.glob("00_E8000399.yaml"))
    assert written
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert doc["variants"][0]["body"]["fields"] == []


def test_extend_empty_pair_with_resp(ext_dir_isolated):
    result = _run_c_struct(
        "查从节点",
        afn="03",
        di="E8030399",
        pair=True,
        description="空请求查询",
        empty_payload=True,
        resp_c_struct_path=str(C_STRUCT_DIR / "query_slave_info_resp.h"),
    )
    assert result["state"] == "SUCCEEDED"
    written = list(ext_dir_isolated.glob("03_E8030399.yaml"))
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert len(doc["variants"]) == 2
    assert doc["variants"][0]["body"]["fields"] == []
    assert len(doc["variants"][1]["body"]["fields"]) == 3


def test_extend_run_log_stages(ext_dir_isolated):
    result = _run_c_struct(
        "C struct 扩展",
        afn="03",
        di=TEST_DI,
        pair=True,
        description="查询从节点信息",
        c_struct_path=str(C_STRUCT_DIR / "query_slave_info_req.h"),
        resp_c_struct_path=str(C_STRUCT_DIR / "query_slave_info_resp.h"),
    )
    assert result["state"] == "SUCCEEDED"
    log_dir = Path(result["log_dir"])
    assert (log_dir / "extend.log").exists()
    stages = {p.name for p in (log_dir / "stages").glob("*.json")}
    assert any("c_struct_parse" in n for n in stages)
    assert any("yaml_preview" in n for n in stages)
    assert any("fidelity" in n for n in stages)
    assert any("draft_result" in n for n in stages)


def test_extend_from_c_struct_pair(ext_dir_isolated):
    result = _run_c_struct(
        "扩展",
        afn="03",
        di=TEST_DI,
        pair=True,
        description="查询从节点信息",
        c_struct_path=str(C_STRUCT_DIR / "query_slave_info_req.h"),
        resp_c_struct_path=str(C_STRUCT_DIR / "query_slave_info_resp.h"),
    )
    assert result["state"] == "SUCCEEDED"
    written = list(ext_dir_isolated.glob(f"03_{TEST_DI}.yaml"))
    assert written
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert len(doc["variants"]) == 2
    down_fields = doc["variants"][0]["body"]["fields"]
    assert down_fields[0]["type"] == "uint16_le"
    up_fields = doc["variants"][1]["body"]["fields"]
    assert up_fields[2]["type"] == "array"
    assert up_fields[2]["count_ref"] == "response_slave_count"


def test_extend_single_variant_enum(ext_dir_isolated):
    result = _run_c_struct(
        "扩展 enum",
        afn="03",
        di=TEST_DI_ENUM,
        dir="uplink",
        description="设备类型枚举示例",
        c_struct_path=str(C_STRUCT_DIR / "device_type_enum.h"),
    )
    assert result["state"] == "SUCCEEDED"
    written = list(ext_dir_isolated.glob(f"03_{TEST_DI_ENUM}.yaml"))
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    field = doc["variants"][0]["body"]["fields"][0]
    assert field["type"] == "enum"


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


def test_yaml_writer_passes_through_c_fields():
    fields = [{"name": "x", "type": "uint16_le", "desc": "test"}]
    spec = ExtensionSpec(
        afn=0x04,
        di=DI_ADD_SLAVE,
        description="添加从节点",
        dir=0,
        add=False,
        fields=fields,
    )
    preview = yaml_writer.render_extension_yaml(spec, "test")
    assert "type: uint16_le" in preview


def test_extend_run_log_class(tmp_path):
    log = ExtendRunLog(tmp_path / "run1")
    log.log_stage("test", {"summary": "hello", "value": 1})
    assert log.log_path.exists()


def test_mcp_tool_call_c_struct(ext_dir_isolated):
    result = call_tool("protocol_extend_run", {
        "raw_input": "扩展",
        "user_input": {
            "afn": "03",
            "di": TEST_DI_NESTED,
            "dir": "uplink",
            "description": "嵌套结构体示例",
            "c_struct_path": str(C_STRUCT_DIR / "nested_date.h"),
        },
    })
    assert result["state"] == "SUCCEEDED"


def test_mcp_stdio_json_lines(ext_dir_isolated):
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "protocol_extend_run",
            "arguments": {
                "raw_input": "扩展",
                "user_input": {
                    "afn": "03",
                    "di": TEST_DI_NESTED,
                    "dir": "uplink",
                    "description": "嵌套结构体示例",
                    "c_struct_path": str(C_STRUCT_DIR / "nested_date.h"),
                },
            },
        },
    }
    raw = json.dumps(request).encode("utf-8") + b"\n"
    output = io.BytesIO()
    code = serve(io.BytesIO(raw), output)
    assert code == 0
    response = json.loads(output.getvalue().decode("utf-8"))
    text = response["result"]["content"][0]["text"]
    assert "SUCCEEDED" in text
