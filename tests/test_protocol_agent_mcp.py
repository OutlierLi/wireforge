import io
import json

from agent_protocol.state_machine import RUNS_DIR, run_agent_protocol
import agent_protocol.state_machine as state_machine
from agent_protocol.protocol_map import ProtocolMapMissingError
from console.handlers.route import handle as route_handle
from mcp_servers.protocol.server import call_tool, handle_message, serve


def _find_entry(protocol_map: dict, suffix: str, **route_params):
    for proto in (protocol_map.get("protocols") or {}).values():
        for entry in proto.get("entries") or []:
            if not (entry.get("leaf_id") or entry.get("id", "")).endswith(suffix):
                continue
            params = entry.get("route_params") or {}
            if all(params.get(key) == value for key, value in route_params.items()):
                return entry
    raise AssertionError(f"entry not found: {suffix} {route_params}")


def _saved_protocol_map(result: dict) -> dict:
    path = RUNS_DIR / result["run_id"] / "protocol_map.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_protocol_task_build_flow_returns_map_then_schema_then_builds():
    first = run_agent_protocol("构造 dlt645 读通信地址请求")

    assert first["state"] == "WAITING_INPUT"
    assert first["need"] == "protocol_match"
    assert first["map_entries"] >= 1
    assert first["candidates"]
    assert "waiting_input" not in first
    protocol_map = _saved_protocol_map(first)
    entry = _find_entry(protocol_map, "read_address_request", proto="dlt645")

    second = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )

    assert second["state"] == "WAITING_INPUT"
    assert second["need"] == "values"
    assert second["fields"] == []

    third = run_agent_protocol(run_id=first["run_id"], user_input={"fields": {}})

    assert third["state"] == "SUCCEEDED"
    assert third["final_frame"] == "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"
    assert third["decode_verified"] is True
    run_dir = RUNS_DIR / third["run_id"]
    assert (run_dir / "raw_input").exists()
    assert (run_dir / "protocol_map.json").exists()
    assert (run_dir / "route.json").exists()
    assert (run_dir / "task_plan.json").exists()
    assert (run_dir / "events").exists()


def test_protocol_task_default_response_fits_compact_budget():
    raw = "构造一个请求集中器的响应报文，时间为当前时间"
    result = run_agent_protocol(raw)

    assert _json_bytes(result) <= max(512, len(raw.encode("utf-8")) * 20)
    assert "waiting_input" not in result
    assert "results" not in result


def test_protocol_task_debug_returns_full_diagnostics():
    result = run_agent_protocol("构造 dlt645 读通信地址请求", debug=True)

    assert result["state"] == "WAITING_INPUT"
    assert result["waiting_input"]["field"] == "protocol_match"
    assert result["waiting_input"]["protocol_map_ref"]["entry_count"] >= 1
    assert "log_dir" in result
    assert "workflow_log" in result
    assert "results" in result


def test_protocol_task_appends_global_workflow_log(tmp_path, monkeypatch):
    workflow_log = tmp_path / "agent_protocol_workflow.log"
    monkeypatch.setattr(state_machine, "LOG_DIR", tmp_path)
    monkeypatch.setattr(state_machine, "WORKFLOW_LOG", workflow_log)

    first = run_agent_protocol("构造 dlt645 读通信地址请求")
    entry = _find_entry(_saved_protocol_map(first), "read_address_request", proto="dlt645")
    second = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )
    result = run_agent_protocol(run_id=first["run_id"], user_input={"fields": {}})

    assert second["need"] == "values"
    assert result["state"] == "SUCCEEDED"
    text = workflow_log.read_text(encoding="utf-8")
    assert "raw_input: 构造 dlt645 读通信地址请求" in text
    assert "step=map_ready" in text
    assert "protocol_map.entries:" in text
    assert "step=route_request" in text
    assert "step=build_request" in text
    assert "step=decode_verify_checked" in text
    assert f"final_frame: {result['final_frame']}" in text
    assert "protocol_map.entries:" in text


def test_protocol_task_reports_missing_protocol_map_cache(monkeypatch):
    def missing_map():
        raise ProtocolMapMissingError("protocol map cache missing: compiled/protocol_map.json. Run `python3 scripts/bootstrap_protocol_cache.py` first.")

    monkeypatch.setattr(state_machine, "_full_protocol_map", missing_map)

    result = run_agent_protocol("构造 dlt645 读通信地址请求")

    assert result["state"] == "FAILED"
    assert "protocol map cache missing" in result["error"]
    assert result["bootstrap"]["required"] is True
    assert result["bootstrap"]["command"] == "python3 scripts/bootstrap_protocol_cache.py"


def test_protocol_task_rejects_reused_run_id_with_different_raw_input():
    first = run_agent_protocol("构造 dlt645 读通信地址请求")

    result = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间", run_id=first["run_id"])

    assert result["state"] == "FAILED"
    assert "different raw_input" in result["error"]
    assert "omit run_id to start a new task" in result["error"]


def test_protocol_task_rejects_fields_before_protocol_match():
    first = run_agent_protocol("构造一个添加从节点的报文，从节点地址为012400038813，012400038824")

    assert first["state"] == "WAITING_INPUT"
    assert first["need"] == "protocol_match"

    second = run_agent_protocol(run_id=first["run_id"], user_input={"fields": {}})

    assert second["state"] == "WAITING_INPUT"
    assert second["need"] == "protocol_match"
    assert "final_frame" not in second
    events = (RUNS_DIR / first["run_id"] / "events").read_text(encoding="utf-8")
    assert "mcp_reject_out_of_order_fields" in events


def test_protocol_task_treats_generic_add_as_build_intent():
    result = run_agent_protocol("添加从节点 CSG2016 afn04")

    assert result["state"] == "WAITING_INPUT"
    assert result["need"] == "protocol_match"
    candidate_ids = [item["id"] for item in result["candidates"]]
    assert any("afn04_add_slave" in item for item in candidate_ids)


def test_protocol_task_candidates_are_diversified_by_leaf():
    result = run_agent_protocol("构造一个添加从节点的报文，从节点地址为012400038813，012400038824")

    leaf_ids = [item["id"].split("::", 1)[0] for item in result["candidates"]]
    assert len(leaf_ids) == len(set(leaf_ids))
    assert "afn04_add_slave" in leaf_ids[0]


def test_csg_concentrator_protocol_map_covers_pdf_table4():
    pdf_table4 = [
        ("00", "E8010001", "downlink", "确认"),
        ("00", "E8010002", "downlink", "否认"),
        ("01", "E8020101", "downlink", "复位硬件"),
        ("01", "E8020102", "downlink", "初始化档案"),
        ("01", "E8020103", "downlink", "初始化任务"),
        ("02", "E8020201", "downlink", "添加任务"),
        ("02", "E8020202", "downlink", "删除任务"),
        ("02", "E8000203", "downlink", "查询未完成任务数"),
        ("02", "E8030204", "downlink", "查询未完成任务列表"),
        ("02", "E8040204", "uplink", "返回查询未完成任务列表"),
        ("02", "E8030205", "downlink", "查询未完成任务详细信息"),
        ("02", "E8040205", "uplink", "返回查询未完成任务详细信息"),
        ("02", "E8000206", "downlink", "查询剩余可分配任务数"),
        ("02", "E8020207", "downlink", "添加多播任务（选配）"),
        ("02", "E8020208", "downlink", "启动任务"),
        ("02", "E8020209", "downlink", "暂停任务"),
        ("03", "E8000301", "downlink", "查询厂商代码和版本信息"),
        ("03", "E8000302", "downlink", "查询本地通信模块运行模式信息"),
        ("03", "E8000303", "downlink", "查询主节点地址"),
        ("03", "E8030304", "downlink", "查询通信延时时长"),
        ("03", "E8040304", "uplink", "返回查询通信延时时长"),
        ("03", "E8000305", "downlink", "查询从节点数量"),
        ("03", "E8030306", "downlink", "查询从节点信息"),
        ("03", "E8040306", "uplink", "返回查询从节点信息"),
        ("03", "E8000307", "downlink", "查询从节点主动注册进度"),
        ("03", "E8030308", "downlink", "查询从节点的父节点"),
        ("03", "E8040308", "uplink", "返回查询从节点的父节点"),
        ("04", "E8020401", "downlink", "设置主节点地址"),
        ("04", "E8020402", "downlink", "添加从节点"),
        ("04", "E8020403", "downlink", "删除从节点"),
        ("04", "E8020404", "downlink", "允许/禁止上报从节点事件"),
        ("04", "E8020405", "downlink", "激活从节点主动注册"),
        ("04", "E8020406", "downlink", "终止从节点主动注册"),
        ("05", "E8050501", "uplink", "上报任务数据"),
        ("05", "E8050502", "uplink", "上报从节点事件"),
        ("05", "E8050503", "uplink", "上报从节点信息"),
        ("05", "E8050504", "uplink", "上报从节点注册结束"),
        ("05", "E8050505", "uplink", "上报任务状态"),
        ("06", "E8060601", "downlink", "请求集中器时间"),
        ("07", "E8020701", "downlink", "启动文件传输"),
        ("07", "E8020702", "downlink", "传输文件内容"),
        ("07", "E8000703", "downlink", "查询文件信息"),
        ("07", "E8000704", "downlink", "查询文件处理进度"),
        ("07", "E8030704", "downlink", "查询文件传输失败节点"),
        ("07", "E8040704", "uplink", "返回查询文件传输失败节点"),
    ]
    first = run_agent_protocol("构造 csg 集中器报文")
    protocol_map = _saved_protocol_map(first)
    csg_entries = protocol_map["protocols"]["csg_2016"]["entries"]

    for afn, di, direction, description in pdf_table4:
        matches = [
            entry
            for entry in csg_entries
            if entry["route_params"].get("afn") == afn
            and entry["route_params"].get("di") == di
            and entry["route_params"].get("dir") == direction
            and entry["route_params"].get("has_address") is False
        ]
        assert matches, f"missing CSG table4 entry: AFN={afn} DI={di}"
        assert matches[0]["description"] == description


def test_protocol_map_entry_ids_include_route_path():
    first = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间")
    protocol_map = _saved_protocol_map(first)
    downlink = _find_entry(protocol_map, "afn06_request_time", proto="csg", dir="downlink", has_address=False)
    uplink = _find_entry(protocol_map, "afn06_request_time_resp", proto="csg", dir="uplink", has_address=False)

    assert downlink["id"] != downlink["leaf_id"]
    assert uplink["id"] != uplink["leaf_id"]
    assert downlink["id"] != uplink["id"]
    assert "::dir=downlink::add=0::afn=06::di=E8060601" in downlink["id"]
    assert downlink["fields"] == []
    assert "::dir=uplink::add=0::afn=06::di=E8060601" in uplink["id"]
    assert "datetime.second" in uplink["fields"]


def test_route_does_not_default_csg_direction():
    result = route_handle({"proto": "csg", "afn": "06", "di": "E8060601"})

    assert result["success"] is False
    assert "multiple routes match" in result["error"]
    assert "dir" in result["error"]


def test_protocol_task_rejects_ambiguous_legacy_leaf_entry_id():
    first = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间")

    result = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": "node:csg_2016.csg_2016.afn06_request_time"},
    )

    assert result["state"] == "FAILED"
    assert "ambiguous protocol map entry" in result["error"]
    assert "Use full entry_id or route_params" in result["error"]


def test_protocol_task_waits_for_missing_values():
    first = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间")
    entry = _find_entry(
        _saved_protocol_map(first),
        "afn06_request_time_resp",
        proto="csg",
        dir="uplink",
    )
    second = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )

    assert second["state"] == "WAITING_INPUT"
    assert second["need"] == "values"
    assert second["fields"] == [
        "datetime.second",
        "datetime.minute",
        "datetime.hour",
        "datetime.day",
        "datetime.month",
        "datetime.year",
    ]

    third = run_agent_protocol(run_id=first["run_id"], user_input={"fields": {"datetime.second": "06"}})

    assert third["state"] == "WAITING_INPUT"
    assert third["need"] == "values"
    assert "datetime.minute" in third["missing_fields"]


def test_protocol_task_builds_csg_concentrator_time_response():
    first = run_agent_protocol("构造一个请求集中器的响应报文，时间为当前时间")
    entry = _find_entry(
        _saved_protocol_map(first),
        "afn06_request_time_resp",
        proto="csg",
        dir="uplink",
    )
    run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )

    result = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"fields": {
            "datetime.second": "06",
            "datetime.minute": "49",
            "datetime.hour": "21",
            "datetime.day": "26",
            "datetime.month": "06",
            "datetime.year": "26",
        }},
    )

    assert result["state"] == "SUCCEEDED"
    assert result["final_frame"]
    assert result["variant_id"] == "csg_2016.afn06_request_time_resp"
    assert result["decode_verified"] is True
    assert result["protocol"] == "csg_2016"
    assert ["afn", True] in result["checks"]
    assert ["di", True] in result["checks"]
    assert ["dir", True] in result["checks"]
    assert ["datetime", True] in result["checks"]


def test_protocol_task_builds_csg_add_slave_with_address_array():
    first = run_agent_protocol("构造一个添加从节点的报文，从节点地址为012400038813，012400038824")
    entry = _find_entry(
        _saved_protocol_map(first),
        "afn04_add_slave",
        proto="csg",
        dir="downlink",
        has_address=False,
    )
    second = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )

    assert second["state"] == "WAITING_INPUT"
    assert second["fields"] == ["slave_count", "slave_addrs"]

    result = run_agent_protocol(
        run_id=first["run_id"],
        user_input={"fields": {
            "slave_count": 2,
            "slave_addrs": ["012400038813", "012400038824"],
        }},
    )

    assert result["state"] == "SUCCEEDED"
    assert result["variant_id"] == "csg_2016.afn04_add_slave"
    assert result["decode_verified"] is True
    assert ["slave_count", True] in result["checks"]
    assert ["slave_addrs", True] in result["checks"]


def test_protocol_task_build_failure_stops_after_three_attempts():
    first = run_agent_protocol("构造 csg 添加任务")
    entry = _find_entry(_saved_protocol_map(first), "afn02_add_task", proto="csg")
    run_agent_protocol(
        run_id=first["run_id"],
        user_input={"entry_id": entry["id"], "route_params": entry["route_params"]},
    )

    bad_fields = {
        "task_id": 1,
        "task_mode_word": 0,
        "timeout_seconds": 30,
        "payload_length": 1,
        "payload": "ZZ",
    }
    one = run_agent_protocol(run_id=first["run_id"], user_input={"fields": bad_fields})
    two = run_agent_protocol(run_id=first["run_id"], user_input={"fields": bad_fields})
    three = run_agent_protocol(run_id=first["run_id"], user_input={"fields": bad_fields})

    assert one["state"] == "WAITING_INPUT"
    assert two["state"] == "WAITING_INPUT"
    assert three["state"] == "FAILED"
    assert "build failed after 3 attempts" in three["error"]


def test_protocol_task_decode_succeeds_for_complete_hex_frame():
    result = run_agent_protocol("解析 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16")

    assert result["state"] == "SUCCEEDED"
    assert result["decode"]["protocol"] == "dlt645_2007"


def test_mcp_tools_list_and_call_protocol_task():
    listed = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert listed is not None
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert "protocol_task_run" in names

    called = call_tool("protocol_task_run", {"raw_input": "解析 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"})

    assert called["state"] == "SUCCEEDED"
    assert called["decode"]["path"].endswith("read_address_request")

    debug_called = call_tool("protocol_task_run", {
        "raw_input": "构造 dlt645 读通信地址请求",
        "debug": True,
    })

    assert debug_called["state"] == "WAITING_INPUT"
    assert debug_called["waiting_input"]["field"] == "protocol_match"


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
