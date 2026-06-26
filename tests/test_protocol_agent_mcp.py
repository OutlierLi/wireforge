import io
import json
from datetime import datetime

from agent_protocol.state_machine import RUNS_DIR, run_agent_protocol
import agent_protocol.state_machine as state_machine
from knowledge_base.store import health, ingest, search
from mcp_servers.protocol.server import call_tool, handle_message, serve


def test_protocol_task_build_auto_decode_verify_succeeds():
    result = run_agent_protocol("构造 dlt645 功能码 13 address AAAAAAAAAAAA")

    assert result["state"] == "SUCCEEDED"
    assert result["results"]["build"]["frame"] == "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"
    assert result["results"]["decode_verify"]["differences"] == []
    run_dir = RUNS_DIR / result["run_id"]
    assert (run_dir / "raw_input").exists()
    assert (run_dir / "context.json").exists()
    assert (run_dir / "task_plan.json").exists()
    assert (run_dir / "events").exists()


def test_protocol_task_appends_global_workflow_log(tmp_path, monkeypatch):
    workflow_log = tmp_path / "agent_protocol_workflow.log"
    monkeypatch.setattr(state_machine, "LOG_DIR", tmp_path)
    monkeypatch.setattr(state_machine, "WORKFLOW_LOG", workflow_log)

    result = run_agent_protocol("构造 dlt645 功能码 13 address AAAAAAAAAAAA")

    assert result["state"] == "SUCCEEDED"
    assert result["workflow_log"] == str(workflow_log)
    text = workflow_log.read_text(encoding="utf-8")
    assert "raw_input: 构造 dlt645 功能码 13 address AAAAAAAAAAAA" in text
    assert "step=context_ready" in text
    assert "context.provider: RagContextProvider" in text
    assert "step=plan_ready" in text
    assert "task_types: BUILD" in text
    assert "pending=[BUILD+DECODE_VERIFY]" in text
    assert "step=build_request" in text
    assert "step=build_result" in text
    assert "success: True" in text
    assert f"final_frame: {result['results']['build']['frame']}" in text
    assert not text.lstrip().startswith("{")


def test_protocol_task_waiting_input_can_resume_with_user_input():
    first = run_agent_protocol("构造报文")

    assert first["state"] == "WAITING_INPUT"
    assert first["waiting_input"]["field"] == "proto"

    second = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"proto": "dlt645", "func": "13", "address": "AAAAAAAAAAAA"},
    )

    assert second["state"] == "SUCCEEDED"
    assert "build" in second["results"]


def test_protocol_task_decode_succeeds_for_complete_hex_frame():
    result = run_agent_protocol("解析 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16")

    assert result["state"] == "SUCCEEDED"
    assert result["results"]["decode"]["protocol"] == "dlt645_2007"


def test_protocol_task_builds_csg_concentrator_time_response_with_current_time(tmp_path, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 26, 21, 49, 6, tzinfo=tz)

    workflow_log = tmp_path / "agent_protocol_workflow.log"
    monkeypatch.setattr(state_machine, "LOG_DIR", tmp_path)
    monkeypatch.setattr(state_machine, "WORKFLOW_LOG", workflow_log)
    monkeypatch.setattr(state_machine, "datetime", FixedDatetime)

    result = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间")

    assert result["state"] == "SUCCEEDED"
    assert result["context"]["deterministic_fields"]["datetime"] == "260626214906"
    assert result["context"]["provider"] == "RagContextProvider"
    assert any("csg_2016/doc" in source for source in result["context"]["sources"])
    assert any("afn_payloads.yaml" in source for source in result["context"]["sources"])
    assert result["context"]["retrieved"]
    build = result["results"]["build"]
    assert build["protocol"] == "csg_2016"
    assert "csg_uplink" in build["path"]
    assert "csg_2016.afn06_request_time_resp" in build["path"]
    assert result["results"]["decode_verify"]["differences"] == []
    checked_fields = {
        item["field"]: item
        for item in result["results"]["decode_verify"]["checked_fields"]
    }
    assert checked_fields["afn"] == {"field": "afn", "expected": "06", "actual": 6, "ok": True}
    assert checked_fields["di"] == {"field": "di", "expected": "E8010601", "actual": "E8 01 06 01", "ok": True}
    assert checked_fields["dir"] == {"field": "dir", "expected": "uplink", "actual": 1, "ok": True}
    assert checked_fields["datetime"] == {"field": "datetime", "expected": "260626214906", "actual": "260626214906", "ok": True}
    values = result["results"]["decode_verify"]["decode"]["values"]
    assert values["user_data"]["di"] == "E8 01 06 01"
    assert values["user_data"]["csg_2016.afn06_group.di_payload"]["datetime"] == "260626214906"
    text = workflow_log.read_text(encoding="utf-8")
    assert "知识库命中" in text
    assert 'context.deterministic_fields: {"datetime":"260626214906"}' in text
    assert "decoded_fields:" in text
    assert "checked_fields:" in text
    assert "  - afn: expected=06 actual=6 ok=True" in text
    assert "  - di: expected=E8010601 actual=E8 01 06 01 ok=True" in text
    assert "  - dir: expected=uplink actual=1 ok=True" in text
    assert "  - datetime: expected=260626214906 actual=260626214906 ok=True" in text


def test_protocol_knowledge_base_searches_protocol_docs():
    ingest(rebuild=True)
    status = health()
    assert status["ok"] is True
    result = search("请求集中器时间 当前时间", top_k=5)
    assert result["results"]
    paths = [item["path"] for item in result["results"]]
    assert any("database/protocols/csg_2016/doc" in path for path in paths)


def test_mcp_tools_list_and_call_protocol_task():
    listed = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert listed is not None
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert "protocol_task_run" in names

    called = call_tool("protocol_task_run", {"raw_input": "解析 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"})

    assert called["state"] == "SUCCEEDED"
    assert called["results"]["decode"]["path"].endswith("read_address_request")


def test_mcp_stdio_content_length_framing():
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "protocol_task_run",
            "arguments": {"raw_input": "解析 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"},
        },
    }
    body = json.dumps(request).encode("utf-8")
    raw = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    output = io.BytesIO()

    code = serve(io.BytesIO(raw), output)

    assert code == 0
    response_body = output.getvalue().split(b"\r\n\r\n", 1)[1]
    response = json.loads(response_body.decode("utf-8"))
    text = response["result"]["content"][0]["text"]
    assert '"state": "SUCCEEDED"' in text


def test_mcp_stdio_json_lines_framing_matches_client():
    request = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    raw = json.dumps(request).encode("utf-8") + b"\n"
    output = io.BytesIO()

    code = serve(io.BytesIO(raw), output)

    assert code == 0
    assert b"Content-Length" not in output.getvalue()
    response = json.loads(output.getvalue().decode("utf-8"))
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert "protocol_task_run" in names
