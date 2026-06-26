import io
import json

from agent_protocol.state_machine import RUNS_DIR, run_agent_protocol
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
