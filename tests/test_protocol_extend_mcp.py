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


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(yaml_writer, "EXTENSIONS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def real_ext_dir(monkeypatch):
    """Write extensions into the real variants/extensions tree for compile/map tests."""
    REAL_EXT_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in ("03_E80304F*.yaml", "03_E80304E*.yaml", "03_E80304F4_*.yaml"):
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
    return run_protocol_extend(run_id=run_id, user_input={"confirm": True})


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
    assert "afn" in result["missing_fields"]
    assert result["partial"].get("di") == HEX_NEW_DI


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


# ── 冲突 / 不支持 ─────────────────────────────────────────────────────────


def test_extend_duplicate_di_downlink_rejected():
    result = run_protocol_extend(
        f"扩展 AFN03 DI={HEX_EXISTING_DI} 查询厂商",
        user_input={
            "dir": "downlink",
            "add": False,
            "description": "重复 DI 测试",
        },
    )

    assert result["state"] == "FAILED"
    assert "conflict" in result["error"].lower()
    assert result.get("conflicts")


def test_extend_duplicate_di_uplink_rejected():
    result = run_protocol_extend(
        f"扩展 AFN03 DI={HEX_EXISTING_DI} 响应厂商",
        user_input={
            "dir": "uplink",
            "add": False,
            "description": "重复上行 DI",
        },
    )

    assert result["state"] == "FAILED"
    assert "conflict" in result["error"].lower()


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
    preview = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI} 查询延时时长",
        dir="downlink",
        add=False,
        description="查询通信延时时长",
        fields=[{"name": "timeout", "type": "uint16_le", "desc": "超时(秒)", "default": 70}],
    )
    assert preview["need"] == "confirm"
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

    written = list(REAL_EXT_DIR.glob(f"*_{HEX_NEW_DI}_*.yaml"))
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
    preview = _params_step(
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
    assert preview["need"] == "confirm"

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    assert result["map_ok"] is True

    written = list(REAL_EXT_DIR.glob(f"*_{HEX_NEW_DI_STRUCT}_*.yaml"))
    real_ext_dir.append(written[0])
    doc = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    body_fields = doc["variants"][0]["body"]["fields"]
    assert body_fields[1]["type"] == "struct"
    assert body_fields[1]["fields"][0]["name"] == "year"


def test_extend_request_response_pair(real_ext_dir):
    preview = _params_step(
        f"扩展 AFN03 DI={HEX_NEW_DI_PAIR} 成对报文",
        add=False,
        description="查询延时时长",
        pair=True,
        resp_description="返回延时时长",
        fields=[{"name": "req_token", "type": "uint8", "desc": "请求令牌"}],
        resp_fields=[{"name": "delay", "type": "uint16_le", "desc": "延时(ms)"}],
    )
    assert preview["need"] == "confirm"
    assert "control.dir: 0" in preview["yaml_preview"]
    assert "control.dir: 1" in preview["yaml_preview"]

    result = _confirm(preview["run_id"])
    assert result["state"] == "SUCCEEDED"
    assert result["map_ok"] is True
    assert len(result["variant_ids"]) >= 2

    written = list(REAL_EXT_DIR.glob(f"*_{HEX_NEW_DI_PAIR}_*.yaml"))
    real_ext_dir.append(written[0])
    text = written[0].read_text(encoding="utf-8")
    assert text.count("kind: variant") >= 2

    for dir_val in (0, 1):
        route = verify_route_handle(
            ExtensionSpec(afn=0x03, di=HEX_NEW_DI_PAIR, add=False),
            dir_value=dir_val,
        )
        assert route["success"] is True


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
    preview = _params_step(
        f"扩展 AFN03 DI={HEX_PREVIEW_DI} 测试预览",
        dir="downlink",
        add=False,
        description="仅预览",
    )
    assert preview["need"] == "confirm"
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
    assert second["need"] == "confirm"

    third = call_tool("protocol_extend_run", {
        "run_id": first["run_id"],
        "user_input": {"confirm": True},
    })
    assert third["state"] == "SUCCEEDED"
    assert third["map_ok"] is True

    written = list(REAL_EXT_DIR.glob("*_E80304F4_*.yaml"))
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
