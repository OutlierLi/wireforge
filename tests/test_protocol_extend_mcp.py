"""Integration tests for protocol_extend_run MCP."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from protocol_extend import run_protocol_extend
from protocol_extend import yaml_writer
from protocol_extend.map_verify import refresh_protocol_map, verify_route_handle
from protocol_extend.fields import field_to_yaml
from protocol_extend.schema import ExtensionSpec, INPUT_SCHEMA
from protocol_extend.validator import find_conflicts
from mcp_servers.extend.server import call_tool, handle_message, serve

ROOT = Path(__file__).resolve().parent.parent
REAL_EXT_DIR = ROOT / "protocol_tool" / "protocols" / "csg_2016" / "variants" / "extensions"
COMPILED_DIR = ROOT / "compiled"

HEX_NEW_DI = "E80304F1"
HEX_PREVIEW_DI = "E80304E1"
HEX_NEW_DI_PAIR = "E80304F2"
HEX_NEW_DI_STRUCT = "E80304F3"
HEX_EXISTING_DI = "E8000301"
HEX_NEW_DI_EVIDENCE = "E80304F5"


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def real_ext_dir(monkeypatch):
    """Write extensions into the real variants/extensions tree for compile/map tests."""
    REAL_EXT_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in (
        "03_E80304F*.yaml",
        "03_E80304E*.yaml",
        "03_E80304F4.yaml",
        "05_E80505A*.yaml",
    ):
        for path in REAL_EXT_DIR.glob(pattern):
            path.unlink(missing_ok=True)
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", REAL_EXT_DIR)
    created: list[Path] = []
    yield created
    for path in created:
        path.unlink(missing_ok=True)
    # Re-compile without test extensions so other tests are not affected.
    try:
        from protocol_tool.compiler.pipeline import compile_protocol
        from agent_protocol.protocol_map import build_protocol_map_from_ir, compact_protocol_map
        import json as _json

        registry = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
        compile_protocol(str(registry), "csg_2016", output_dir=str(COMPILED_DIR))
        refresh_protocol_map(COMPILED_DIR)
    except Exception:
        pass


def _schema_item(name: str) -> dict:
    for item in INPUT_SCHEMA:
        if item["name"] == name:
            return item
    raise KeyError(name)


def _params_step(raw: str, **user_input) -> dict:
    first = run_protocol_extend(raw)
    if not user_input:
        return first
    return run_protocol_extend(run_id=first["run_id"], user_input=user_input)


def _confirm(run_id: str) -> dict:
    return run_protocol_extend(run_id=run_id, user_input={"action": "accept"})


def _start_review(run_id: str) -> dict:
    return run_protocol_extend(run_id=run_id, user_input={"action": "start"})


def _to_message_review(run_id: str, **user_input) -> dict:
    """After collection_ready, start review and return message_review (or field_types)."""
    started = _start_review(run_id)
    if started["need"] != "collection_ready":
        return started
    return run_protocol_extend(run_id=run_id, user_input=user_input or {"action": "start"})


def _params_to_review(raw: str, **user_input) -> dict:
    """Fill params if needed, reach collection_ready, then start → message_review."""
    first = run_protocol_extend(raw)
    rid = first["run_id"]
    if first["need"] == "params" and user_input:
        first = run_protocol_extend(run_id=rid, user_input=user_input)
    if first["need"] != "collection_ready":
        return first
    return _start_review(rid)


def _written_yaml(ext_dir: Path) -> dict:
    files = list(ext_dir.glob("*.yaml"))
    assert files, "no extension yaml written"
    return yaml.safe_load(files[0].read_text(encoding="utf-8"))


# ── 参数缺失 / 不明确 ─────────────────────────────────────────────────────


def test_extend_vague_input_missing_core_params():
    result = run_protocol_extend("帮我扩展一个新报文")

    assert result["state"] == "WAITING_INPUT"
    assert result["need"] == "params"
    for field in ("afn", "di", "description"):
        assert field in result["missing_fields"]


def test_extend_missing_di():
    result = run_protocol_extend("扩展 CSG AFN03 查询延时时长")

    assert result["need"] == "params"
    assert "di" in result["missing_fields"]
    assert result["partial"].get("afn") == "03"


def test_extend_missing_afn():
    result = run_protocol_extend(f"扩展 CSG DI={HEX_NEW_DI} 查询延时时长")

    assert result["need"] == "params"
    assert "afn" not in result["missing_fields"]
    assert result["partial"].get("di") == HEX_NEW_DI
    assert result["partial"].get("afn") == "03"


def test_extend_missing_description():
    result = run_protocol_extend(f"扩展 CSG AFN03 DI={HEX_NEW_DI}")

    assert result["need"] == "params"
    assert "description" in result["missing_fields"]
    assert "dir" in result["missing_fields"]
    assert "add" in result["missing_fields"]


def test_extend_missing_dir_and_add():
    result = run_protocol_extend(f"扩展 CSG 报文 AFN03 DI={HEX_NEW_DI}，查询延时时长")

    assert result["state"] == "WAITING_INPUT"
    assert result["need"] == "params"
    assert "dir" in result["missing_fields"]
    assert "add" in result["missing_fields"]
    assert result["partial"]["di"] == HEX_NEW_DI


def test_extend_missing_dir_only():
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_PREVIEW_DI} 查询延时")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={"add": False, "description": "查询延时时长"},
    )

    assert second["need"] == "params"
    assert second["missing_fields"] == ["dir"]


def test_extend_missing_add_only():
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_NEW_DI} 下行 查询延时")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={"dir": "downlink", "description": "查询延时时长"},
    )

    assert second["need"] == "params"
    assert "add" in second["missing_fields"]


def test_extend_partial_includes_schema_defaults():
    result = run_protocol_extend(f"扩展 AFN03 DI={HEX_NEW_DI}")

    assert result["partial"]["protocol"] == _schema_item("protocol")["default"]
    assert result["input_schema"]
    protocol_field = _schema_item("protocol")
    assert protocol_field["default"] == "csg"
    assert protocol_field["desc"]


def test_extend_fields_missing_desc():
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_NEW_DI}")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "查询延时时长",
            "fields": [{"name": "timeout", "type": "uint16_le"}],
        },
    )

    assert second["need"] == "params"
    assert "fields[0].desc" in second["missing_fields"]


def test_extend_struct_field_missing_child_desc():
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_NEW_DI}")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "查询版本",
            "fields": [{
                "name": "version_date",
                "type": "struct",
                "desc": "版本日期",
                "fields": [{"name": "year", "type": "bcd", "length": 1}],
            }],
        },
    )

    assert second["need"] == "params"
    assert "fields[0].fields[0].desc" in second["missing_fields"]


def test_extend_array_struct_fields_to_yaml():
    fields = [
        {"name": "node_count", "type": "uint8", "desc": "节点数量"},
        {
            "name": "nodes",
            "type": "array",
            "count_ref": "node_count",
            "item_type": "struct",
            "item_name": "node",
            "desc": "未识别节点列表",
            "item_fields": [
                {"name": "address", "type": "bcd", "length": 6, "byte_order": "little", "desc": "地址"},
                {"name": "device_type", "type": "uint8", "desc": "设备类型"},
            ],
        },
    ]
    yaml_fields = [field_to_yaml(f) for f in fields]
    assert yaml_fields[1]["type"] == "array"
    assert yaml_fields[1]["count_ref"] == "node_count"
    assert yaml_fields[1]["item_type"] == "struct"
    assert yaml_fields[1]["item_params"]["fields"][0]["name"] == "address"
    assert yaml_fields[1]["item_params"]["fields"][1]["type"] == "uint8"

    spec = ExtensionSpec(
        afn=0x05,
        di="E80505A0",
        description="上报未识别节点信息",
        dir=1,
        add=False,
        fields=fields,
    )
    preview = yaml_writer.render_extension_yaml(spec, "test")
    assert "count_ref: node_count" in preview
    assert "item_type: struct" in preview
    assert "device_type" in preview
    assert "type: bytes" not in preview


def test_extend_array_primitive_fields_to_yaml():
    fields = [
        {"name": "node_count", "type": "uint8", "desc": "数量"},
        {
            "name": "node_addrs",
            "type": "array",
            "count_ref": "node_count",
            "item_type": "node_address",
            "item_name": "node_addr",
            "desc": "节点地址列表",
        },
    ]
    yaml_fields = [field_to_yaml(f) for f in fields]
    assert yaml_fields[1]["item_type"] == "node_address"
    assert "item_params" not in yaml_fields[1]


def test_extend_ascii_field_keeps_byte_order():
    yaml_field = field_to_yaml({
        "name": "vendor_code",
        "type": "ascii",
        "length": 2,
        "byte_order": "little",
        "desc": "厂商代码",
    })
    assert yaml_field["type"] == "ascii"
    assert yaml_field["byte_order"] == "little"


def test_extend_array_missing_count_ref():
    first = run_protocol_extend(f"扩展 AFN05 DI=E80505A0")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={
            "dir": "uplink",
            "add": False,
            "description": "上报节点",
            "fields": [
                {"name": "node_count", "type": "uint8", "desc": "数量"},
                {"name": "nodes", "type": "array", "item_type": "struct", "desc": "列表"},
            ],
        },
    )
    assert second["need"] == "params"
    assert "fields[1].count_ref" in second["missing_fields"]


def test_extend_array_struct_missing_item_fields():
    first = run_protocol_extend(f"扩展 AFN05 DI=E80505A0")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={
            "dir": "uplink",
            "add": False,
            "description": "上报节点",
            "fields": [
                {"name": "node_count", "type": "uint8", "desc": "数量"},
                {
                    "name": "nodes",
                    "type": "array",
                    "count_ref": "node_count",
                    "item_type": "struct",
                    "desc": "列表",
                },
            ],
        },
    )
    assert second["need"] == "params"
    assert "fields[1].item_fields" in second["missing_fields"]


def test_extend_params_includes_field_dsl_examples():
    result = run_protocol_extend(f"扩展 AFN05 DI=E80505A0")
    examples = result.get("field_dsl_examples") or []
    assert any(ex.get("type") == "array" for ex in examples)


# ── 冲突 / 不支持 ─────────────────────────────────────────────────────────


def test_extend_duplicate_di_downlink_rejected():
    first = run_protocol_extend(
        f"扩展 AFN03 DI={HEX_EXISTING_DI} 查询厂商",
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "重复 DI 测试",
        },
    )
    assert first["need"] == "collection_ready"
    review = _start_review(first["run_id"])
    assert review["need"] == "message_review"
    assert review.get("last_error") or review.get("error")
    assert review.get("conflicts") or "conflict" in (review.get("last_error") or review.get("error") or "").lower()

    accept = _confirm(review["run_id"])
    assert accept["state"] == "WAITING_INPUT"
    assert "conflict" in (accept.get("error") or accept.get("last_error") or "").lower()


def test_extend_duplicate_di_uplink_rejected():
    first = run_protocol_extend(
        f"扩展 AFN03 DI={HEX_EXISTING_DI} 响应厂商",
        user_input={
            "dir": "uplink",
            "add": False,
            "description": "重复上行 DI",
        },
    )
    assert first["need"] == "collection_ready"
    review = _start_review(first["run_id"])
    assert review["need"] == "message_review"
    accept = _confirm(review["run_id"])
    assert accept["state"] == "WAITING_INPUT"
    assert "conflict" in (accept.get("error") or "").lower()


def test_extend_unsupported_afn():
    result = run_protocol_extend(
        "扩展 AFN08 DI=E8080001 新功能",
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "不支持 AFN",
        },
    )

    assert result["state"] == "FAILED"
    assert "00" in result["error"] or "08" in result["error"]


def test_find_conflicts_existing():
    spec = ExtensionSpec(
        afn=0x03,
        di=HEX_EXISTING_DI,
        description="x",
        dir=0,
        add=False,
    )
    assert find_conflicts(spec)


# ── 成功路径：预览 → 写入 → compile → map → route ─────────────────────────


def test_extend_success_single_downlink(real_ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI} 查询延时时长",
        dir="downlink",
        add=False,
        description="查询通信延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)", "default": 70}],
    )
    assert ready["need"] == "collection_ready"
    preview = _start_review(ready["run_id"])
    assert preview["need"] == "message_review"
    assert preview["yaml_preview"]
    assert "timeout" in preview["yaml_preview"]
    assert "default: 70" in preview["yaml_preview"]
    assert "desc: 超时(秒)" in preview["yaml_preview"]

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    assert result["compile_ok"] is True
    assert result["map_ok"] is True
    assert result["route_entries"]
    assert result["variant_ids"]
    assert (COMPILED_DIR / "protocol_map.yaml").exists()
    yaml_text = (COMPILED_DIR / "protocol_map.yaml").read_text(encoding="utf-8")
    assert HEX_NEW_DI in yaml_text
    assert any("down" in vid for vid in result["variant_ids"])

    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI}.yaml"))
    assert written
    real_ext_dir.append(written[0])

    route = verify_route_handle(
        ExtensionSpec(afn=0x03, di=HEX_NEW_DI, add=False, dir=0),
        dir_value=0,
    )
    assert route["success"] is True

    protocol_map = refresh_protocol_map(COMPILED_DIR)
    entries = [
        e
        for proto in protocol_map.get("protocols", {}).values()
        for e in proto.get("entries", [])
        if HEX_NEW_DI in json.dumps(e)
    ]
    assert entries


def test_extend_success_struct_fields(real_ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI_STRUCT} 查询版本",
        dir="downlink",
        add=False,
        description="查询版本信息",
        fields=[
            {"name": "vendor_code", "type": "ascii", "length": 2, "desc": "厂商代码"},
            {
                "name": "version_date",
                "type": "struct",
                "desc": "版本日期",
                "fields": [
                    {"name": "year", "type": "bcd", "length": 1, "desc": "年"},
                    {"name": "month", "type": "bcd", "length": 1, "desc": "月"},
                ],
            },
        ],
    )
    assert ready["need"] == "collection_ready"
    preview = _start_review(ready["run_id"])
    assert preview["need"] == "message_review"

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    assert result["map_ok"] is True

    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI_STRUCT}.yaml"))
    real_ext_dir.append(written[0])
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    body_fields = doc["variants"][0]["body"]["fields"]
    assert body_fields[1]["type"] == "struct"
    assert body_fields[1]["fields"][0]["name"] == "year"


def test_extend_request_response_pair(real_ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI_PAIR} 成对报文",
        add=False,
        description="查询延时时长",
        pair=True,
        resp_description="返回延时时长",
        fields=[{"name": "req_token", "type": "uint8", "desc": "请求令牌"}],
        resp_fields=[{"name": "delay", "type": "uint16_le", "desc": "延时(ms)"}],
    )
    assert ready["need"] == "collection_ready"
    preview = _start_review(ready["run_id"])
    assert preview["need"] == "message_review"
    assert "control.dir: 0" in preview["yaml_preview"]
    assert "control.dir: 1" in preview["yaml_preview"]

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    assert result["map_ok"] is True
    assert len(result["variant_ids"]) >= 2

    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI_PAIR}.yaml"))
    real_ext_dir.append(written[0])
    text = written[0].read_text(encoding="utf-8")
    assert text.count("kind: variant") >= 2

    for dir_val in (0, 1):
        route = verify_route_handle(
            ExtensionSpec(afn=0x03, di=HEX_NEW_DI_PAIR, add=False),
            dir_value=dir_val,
        )
        assert route["success"] is True


def test_extension_filename_format():
    spec = ExtensionSpec(afn=0x03, di="E80304F1", description="查询延时时长", dir=0, add=False)
    assert yaml_writer.extension_filename(spec) == "03_E80304F1.yaml"
    spec5 = ExtensionSpec(afn=0x05, di="e80505a0", description="上报节点", dir=1, add=False)
    assert yaml_writer.extension_filename(spec5) == "05_E80505A0.yaml"


def test_extension_filename_rejects_invalid_di():
    spec = ExtensionSpec(afn=0x03, di="A80304F1", description="x", dir=0, add=False)
    with pytest.raises(ValueError, match="E8"):
        yaml_writer.extension_filename(spec)
    short = ExtensionSpec(afn=0x03, di="E80304", description="x", dir=0, add=False)
    with pytest.raises(ValueError, match="8 hex"):
        yaml_writer.extension_filename(short)


def test_extend_fields_to_yaml_unit():
    spec = ExtensionSpec(
        protocol="csg_2016",
        afn=0x03,
        di=HEX_NEW_DI,
        description="测试",
        dir=0,
        add=False,
        fields=[
            {"name": "vendor_code", "type": "ascii", "length": 2, "desc": "厂商"},
            {
                "name": "version_date",
                "type": "struct",
                "desc": "版本",
                "fields": [
                    {"name": "year", "type": "bcd", "length": 1, "desc": "年"},
                ],
            },
        ],
    )
    variants = yaml_writer.build_variants(spec)
    fields = variants[0]["body"]["fields"]
    assert fields[0]["desc"] == "厂商"
    assert fields[1]["fields"][0]["desc"] == "年"


def test_extend_preview_does_not_write_file(ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_PREVIEW_DI} 测试预览",
        dir="downlink",
        add=False,
        description="仅预览",
    )
    assert ready["need"] == "collection_ready"
    assert list(ext_dir.glob("*.yaml")) == []
    preview = _start_review(ready["run_id"])
    assert preview["need"] == "message_review"
    assert preview["yaml_preview"]
    assert list(ext_dir.glob("*.yaml")) == []


def test_extend_confirm_without_preview_params_still_waits(ext_dir):
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_PREVIEW_DI}")
    second = run_protocol_extend(run_id=first["run_id"], user_input={"confirm": True})
    assert second["need"] == "params"


# ── MCP 层 ───────────────────────────────────────────────────────────────


def test_mcp_tools_list_and_call(real_ext_dir):
    listed = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in listed["result"]["tools"]]
    assert "protocol_extend_run" in names

    first = call_tool("protocol_extend_run", {
        "raw_input": f"扩展 AFN03 DI=E80304F4 测试 MCP",
    })
    assert first["need"] == "params"

    second = call_tool("protocol_extend_run", {
        "run_id": first["run_id"],
        "user_input": {
            "dir": "downlink",
            "add": False,
            "description": "MCP 测试",
        },
    })
    assert second["need"] == "collection_ready"

    third = call_tool("protocol_extend_run", {
        "run_id": first["run_id"],
        "user_input": {"action": "start"},
    })
    assert third["need"] == "message_review"

    fourth = call_tool("protocol_extend_run", {
        "run_id": first["run_id"],
        "user_input": {"confirm": True},
    })
    assert fourth["state"] == "SUCCEEDED"
    assert fourth["map_ok"] is True

    written = list(REAL_EXT_DIR.glob("03_E80304F4.yaml"))
    real_ext_dir.append(written[0])


def test_mcp_stdio_json_lines():
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "protocol_extend_run",
            "arguments": {"raw_input": "扩展 AFN03 DI=E80304FE 测试"},
        },
    }
    raw = json.dumps(request).encode("utf-8") + b"\n"
    output = io.BytesIO()
    code = serve(io.BytesIO(raw), output)
    assert code == 0
    response = json.loads(output.getvalue().decode("utf-8"))
    text = response["result"]["content"][0]["text"]
    assert "WAITING_INPUT" in text or "params" in text


def test_extend_evidence_driven_device_type_enum(real_ext_dir):
    """Evidence with value table → enum in YAML, not bare uint8."""
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI_EVIDENCE} 查询设备类型",
        dir="downlink",
        add=False,
        description="查询设备类型",
        fields=[{
            "name": "device_type",
            "desc": "设备类型",
            "bytes": 2,
            "type": "uint8",
            "evidence": [
                "00H：单相表",
                "01H：三相表",
                "02H：采集器",
            ],
        }],
    )
    assert ready["need"] == "collection_ready"
    preview = _start_review(ready["run_id"])
    assert preview.get("inference_report") or preview["need"] in ("message_review", "field_types")
    report = preview.get("inference_report") or []
    if report:
        assert report[0]["semantic_type"] == "enum"
    assert preview["need"] in ("message_review", "field_types")
    assert "type: enum" in preview["yaml_preview"]
    assert "单相表" in preview["yaml_preview"]
    assert "type: uint8" not in preview["yaml_preview"]

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI_EVIDENCE}.yaml"))
    real_ext_dir.append(written[0])
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    field = doc["variants"][0]["body"]["fields"][0]
    assert field["type"] == "enum"
    assert field["values"][0] == "单相表"


def test_extend_unknown_field_type_warning(ext_dir, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", ext_dir)
    first = run_protocol_extend(f"扩展 AFN03 DI=E80304F6 未知字段")
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "未知字段测试",
            "fields": [{"name": "mystery", "desc": "无证据字段"}],
        },
    )
    assert second["need"] == "collection_ready"
    third = _start_review(second["run_id"])
    assert third["need"] in ("field_types", "message_review")
    warnings = third.get("field_type_warnings") or []
    report = third.get("inference_report") or []
    if third["need"] == "field_types":
        assert report and report[0]["semantic_type"] == "unknown"
        assert warnings
    fourth = run_protocol_extend(run_id=first["run_id"], user_input={"confirm": True})
    assert fourth["state"] in ("SUCCEEDED", "WAITING_INPUT", "FAILED")


DOCX_FIXTURE = ROOT / "tests" / "fixtures" / "csg_sample.docx"
DOCX_DI = "E80304F5"


@pytest.fixture
def docx_fixture():
    pytest.importorskip("docx")
    if not DOCX_FIXTURE.exists():
        from tests.fixtures.build_sample_docx import build_sample_docx
        build_sample_docx(DOCX_FIXTURE)
    return DOCX_FIXTURE


def test_extend_from_docx_select_message(docx_fixture):
    first = run_protocol_extend(
        "从 DOCX 扩展 CSG 报文",
        user_input={"document_path": str(DOCX_FIXTURE.relative_to(ROOT))},
    )
    assert first["state"] == "WAITING_INPUT"
    assert first["need"] == "collection_ready"
    drafts = first.get("message_drafts") or []
    assert drafts
    assert first.get("collection_summary")
    assert first.get("scan_summary") or first.get("document_ir_summary") is not None


def test_extend_from_docx_full_flow(real_ext_dir, docx_fixture):
    first = run_protocol_extend(
        "从 DOCX 扩展 CSG 报文",
        user_input={"document_path": str(DOCX_FIXTURE.relative_to(ROOT))},
    )
    assert first["need"] == "collection_ready"
    rid = first["run_id"]
    review = _start_review(rid)
    while review.get("need") == "message_review" and review.get("current_draft", {}).get("di") != DOCX_DI:
        review = run_protocol_extend(run_id=rid, user_input={"action": "skip"})
    if review["need"] == "params":
        review = run_protocol_extend(
            run_id=rid,
            user_input={"dir": "downlink", "add": False, "draft_index": review.get("draft_index", 0)},
        )
    if review["need"] == "field_types":
        review = run_protocol_extend(run_id=rid, user_input={"action": "accept"})
    elif review["need"] == "message_review":
        review = run_protocol_extend(run_id=rid, user_input={"action": "accept"})
    else:
        review = run_protocol_extend(run_id=rid, user_input={"action": "accept"})

    while review.get("state") == "WAITING_INPUT" and review.get("need") in ("message_review", "field_types"):
        if review.get("need") == "field_types":
            review = run_protocol_extend(run_id=rid, user_input={"action": "accept"})
        else:
            review = run_protocol_extend(run_id=rid, user_input={"action": "skip"})

    assert review["state"] == "SUCCEEDED"
    assert review.get("batch_summary")
    written = list(REAL_EXT_DIR.glob(f"03_{DOCX_DI}.yaml"))
    assert written
    real_ext_dir.append(written[0])
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    field = doc["variants"][0]["body"]["fields"][0]
    assert field["type"] == "enum"
    assert "单相表" in str(field.get("values", {}))


def test_extend_two_phase_manual_flow(ext_dir):
    """Phase1 collection_ready → Phase2 message_review → accept."""
    first = run_protocol_extend(f"扩展 AFN03 DI={HEX_PREVIEW_DI} 两阶段测试")
    assert first["need"] == "params"
    second = run_protocol_extend(
        run_id=first["run_id"],
        user_input={"dir": "downlink", "add": False, "description": "两阶段"},
    )
    assert second["need"] == "collection_ready"
    assert len(second["message_drafts"]) == 1
    third = _start_review(second["run_id"])
    assert third["need"] == "message_review"
    assert third["progress"]["total"] == 1
    assert list(ext_dir.glob("*.yaml")) == []


def test_extend_modify_then_accept(real_ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI} 修改后接受",
        dir="downlink",
        add=False,
        description="查询延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    review = _start_review(ready["run_id"])
    modified = run_protocol_extend(
        run_id=ready["run_id"],
        user_input={
            "action": "modify",
            "modify_reason": "默认值应为70秒",
            "fields": [{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)", "default": 70}],
        },
    )
    assert modified["need"] == "message_review"
    assert modified.get("modify_history")
    assert "default: 70" in modified["yaml_preview"]
    result = _confirm(modified["run_id"])
    assert result["state"] == "SUCCEEDED"
    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI}.yaml"))
    real_ext_dir.append(written[0])


def test_extend_confirm_compat_maps_to_accept(real_ext_dir):
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI} confirm兼容",
        dir="downlink",
        add=False,
        description="confirm 兼容",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    review = _start_review(ready["run_id"])
    result = run_protocol_extend(run_id=review["run_id"], user_input={"confirm": True})
    assert result["state"] == "SUCCEEDED"
    written = list(REAL_EXT_DIR.glob(f"03_{HEX_NEW_DI}.yaml"))
    real_ext_dir.append(written[0])


MULTI_DOCX = ROOT / "tests" / "fixtures" / "csg_multi_message.docx"


@pytest.fixture
def multi_docx_fixture():
    pytest.importorskip("docx")
    if not MULTI_DOCX.exists():
        from tests.fixtures.build_multi_message_docx import build_multi_message_docx
        build_multi_message_docx(MULTI_DOCX)
    return MULTI_DOCX


def test_extend_from_docx_multi_message_batch(real_ext_dir, multi_docx_fixture):
    first = run_protocol_extend(
        "从多报文 DOCX 批量扩展",
        user_input={"document_path": str(MULTI_DOCX.relative_to(ROOT))},
    )
    assert first["need"] == "collection_ready"
    assert first["collection_summary"]["total"] >= 2
    rid = first["run_id"]
    review = _start_review(rid)
    while review.get("need") == "field_types":
        review = run_protocol_extend(run_id=rid, user_input={"force_field_types": True})
    assert review["need"] == "message_review"
    assert review["progress"]["total"] >= 2
    accepted = run_protocol_extend(run_id=rid, user_input={"action": "accept"})
    assert accepted["progress"]["accepted"] == 1
    if accepted["need"] == "field_types":
        accepted = run_protocol_extend(run_id=rid, user_input={"force_field_types": True})
    assert accepted["need"] == "message_review"
    skipped = run_protocol_extend(run_id=rid, user_input={"action": "skip", "skip_reason": "暂不扩展"})
    while skipped.get("need") in ("message_review", "field_types"):
        if skipped.get("need") == "field_types":
            skipped = run_protocol_extend(run_id=rid, user_input={"force_field_types": True})
        else:
            skipped = run_protocol_extend(run_id=rid, user_input={"action": "skip"})
    assert skipped["state"] == "SUCCEEDED"
    summary = skipped["batch_summary"]
    assert summary["accepted"] == 1
    assert summary["skipped"] >= 1
    written = list(REAL_EXT_DIR.glob("05_E80505A*.yaml"))
    for path in written:
        real_ext_dir.append(path)
    assert summary["items"][0].get("fidelity_confidence") in ("high", "medium", "low", None)


def test_collection_ready_includes_source_excerpt(ext_dir, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", ext_dir)
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI}",
        dir="downlink",
        add=False,
        description="查询延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    assert ready["need"] == "collection_ready"
    draft = ready["message_drafts"][0]
    assert draft.get("source_excerpt")
    assert draft.get("field_details")
    assert draft["field_details"][0]["name"] == "timeout"


def test_message_review_includes_fidelity_preview(ext_dir, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", ext_dir)
    ready = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI}",
        dir="downlink",
        add=False,
        description="查询延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    review = _start_review(ready["run_id"])
    assert review.get("fidelity_preview")
    assert review.get("source_excerpt")
    assert review.get("variant_plan")


def test_fidelity_blocks_accept_without_force(real_ext_dir):
    di = "E80304E8"
    ready = _params_step(
        f"扩展 AFN03 DI={di}",
        dir="downlink",
        add=False,
        description="查询延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    _start_review(ready["run_id"])
    run_protocol_extend(
        run_id=ready["run_id"],
        user_input={"action": "modify", "description": "与快照完全无关的描述xyz"},
    )
    review2 = run_protocol_extend(run_id=ready["run_id"], user_input={"action": "accept"})
    assert review2["state"] == "WAITING_INPUT"
    assert "fidelity below threshold" in (review2.get("error") or "")


def test_force_fidelity_allows_accept(real_ext_dir):
    di = "E80304E9"
    ready = _params_step(
        f"扩展 AFN03 DI={di}",
        dir="downlink",
        add=False,
        description="查询延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}],
    )
    _start_review(ready["run_id"])
    run_protocol_extend(
        run_id=ready["run_id"],
        user_input={"action": "modify", "description": "故意不一致的描述"},
    )
    result = run_protocol_extend(
        run_id=ready["run_id"],
        user_input={"action": "accept", "force_fidelity": True},
    )
    assert result["state"] == "SUCCEEDED"
    written = list(REAL_EXT_DIR.glob(f"03_{di}.yaml"))
    real_ext_dir.append(written[0])

