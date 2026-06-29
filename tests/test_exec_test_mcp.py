from __future__ import annotations

import json
from pathlib import Path

import yaml

from mcp_servers.exec_test.server import call_tool
from test_runner.exec_command import ExecCommand
from test_runner.execution_report import (
    build_execution_report,
    extract_serial_trace,
    group_comm_interactions,
    render_execution_report_md,
)
from test_runner.context import RunContext, StepRecord
from datetime import datetime, timezone


def test_exec_schema():
    schema = ExecCommand.schema()
    assert schema["role"] == "execution_test"
    assert "optional_execution_fields" in schema["test_plan_schema"]
    assert schema["execution_template"].endswith("execution_test_plan.yaml")


def test_execution_report_build():
    ctx = RunContext(
        run_id="demo_20260101_120000",
        plan_name="demo",
        plan_path=None,
        report_dir=Path("/tmp/demo"),
        start_time=datetime.now(timezone.utc),
        deadline_monotonic=None,
        vars={"port": "/dev/ttyUSB0", "conn": "cco"},
        records=[
            StepRecord(
                "send_init",
                "send",
                "ok",
                12,
                result={
                    "schema": "protocol-tui.v1",
                    "status": "success",
                    "data": {"hex": "68 0C 00 40"},
                },
            ),
        ],
    )
    plan = {
        "version": 1,
        "name": "demo",
        "purpose": "验证初始化",
        "expected_results": [{"step_id": "wait_ack", "description": "收到确认"}],
        "test_flow": ["connect", "send", "wait"],
    }
    report = build_execution_report(
        ctx=ctx,
        plan=plan,
        status="success",
        total_ms=12,
    )
    assert report["test_metadata"]["purpose"] == "验证初始化"
    assert report["serial_trace"][0]["tx_hex"] == "68 0C 00 40"
    assert report["error_analysis"]["status"] == "pass"


def test_render_execution_report_md_business_template():
    report = {
        "name": "demo",
        "status": "success",
        "test_metadata": {
            "purpose": "CCO 添加从节点后，STA 返回表地址。\nCCO 回复确认后，STA 成功入网。",
            "expected_results": [
                {"step_id": "wait_ack", "description": "STA 返回表地址"},
                {"step_id": "wait_join", "description": "STA 成功入网"},
            ],
        },
        "comm_interactions": [
            {
                "index": 1,
                "title": "添加从节点",
                "step_id": "wait_ack",
                "status": "ok",
                "frames": [
                    {"dir": "TX", "hex": "68 AA 16", "timestamp": "14:23:15.123"},
                    {"dir": "RX", "hex": "68 BB 16", "timestamp": "14:23:15.284"},
                ],
            }
        ],
        "steps": [
            {"id": "wait_ack", "status": "ok"},
            {"id": "wait_join", "status": "ok"},
        ],
        "error_analysis": {"status": "pass"},
    }
    md = render_execution_report_md(report)
    assert md.startswith("# 测试报告")
    assert "## 测试目的" in md
    assert "验证：" in md
    assert "CCO 添加从节点后" in md
    assert "✅ 通过" in md
    assert "## 通信记录" in md
    assert "### 交互 1：添加从节点" in md
    assert "[TX][14:23:15.123]" in md
    assert "68 AA 16" in md
    assert "[RX][14:23:15.284]" in md
    assert "## 业务验证" in md
    assert "✅ STA 返回表地址" in md
    assert "## 结论" in md
    assert "本次测试验证通过。" in md
    assert "Run ID" not in md
    assert "步骤执行结果" not in md


def test_group_comm_interactions_send_wait():
    started = "2026-06-29T20:55:51+08:00"
    records = [
        StepRecord(
            "send_init",
            "send",
            "ok",
            10,
            result={"status": "success", "data": {"sent": "68 0C 16"}},
        ),
        StepRecord(
            "wait_init_ack",
            "wait-frame",
            "ok",
            50,
            result={"status": "success", "data": {"frame_hex": "68 0E 16", "matched": True}},
        ),
    ]
    meta = {
        "expected_results": [
            {"step_id": "wait_init_ack", "description": "收到初始化确认"},
        ]
    }
    groups = group_comm_interactions(records, meta, started_at=started)
    assert len(groups) == 1
    assert groups[0]["title"] == "收到初始化确认"
    assert groups[0]["frames"][0]["dir"] == "TX"
    assert groups[0]["frames"][1]["dir"] == "RX"


def test_extract_serial_trace_request_response():
    record = StepRecord(
        "req_step",
        "request",
        "fail",
        100,
        error="timeout",
        result={
            "status": "execution_error",
            "error": "timeout",
            "data": {
                "request": {"frame_hex": "AA BB", "decoded": {"afn": 1}},
                "response": None,
            },
            "detail": {"received_frames": 0, "last_decoded": None},
        },
    )
    trace = extract_serial_trace([record])
    assert len(trace) == 1
    assert trace[0]["tx_hex"] == "AA BB"
    assert trace[0]["received_frames"] == 0


def test_exec_run_mock_generates_execution_report(tmp_path):
    plan = {
        "version": 1,
        "name": "exec_mock",
        "purpose": "mock 自检",
        "test_flow": ["connect", "disconnect"],
        "vars": {"port": "mock://auto", "conn": "cco", "baudrate": 9600},
        "setup": [
            {
                "id": "connect",
                "action": "serial.connect",
                "args": {"conn": "${conn}", "port": "${port}", "baudrate": "${baudrate}"},
            }
        ],
        "steps": [],
        "teardown": [
            {"id": "disconnect", "action": "serial.disconnect", "args": {"conn": "${conn}"}},
        ],
    }
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    report_dir = tmp_path / "exec_report"

    result = ExecCommand.run(
        file=str(path),
        options={"report": str(report_dir), "vars": {"port": "mock://auto"}},
    )
    assert result.get("ok") is True
    assert (report_dir / "execution_report.json").exists()
    assert (report_dir / "execution_report.md").exists()

    er = json.loads((report_dir / "execution_report.json").read_text(encoding="utf-8"))
    assert er["test_metadata"]["purpose"] == "mock 自检"
    assert er["status"] == "success"
    md = (report_dir / "execution_report.md").read_text(encoding="utf-8")
    assert md.startswith("# 测试报告")
    assert "## 测试目的" in md


def test_exec_mcp_call_tool_schema():
    result = call_tool("exec_test.schema", {})
    assert result["role"] == "execution_test"


def test_exec_read_report(tmp_path):
    plan = {
        "version": 1,
        "name": "read_back",
        "purpose": "读报告",
        "vars": {"port": "mock://auto", "conn": "cco", "baudrate": 9600},
        "setup": [
            {
                "id": "connect",
                "action": "serial.connect",
                "args": {"conn": "${conn}", "port": "${port}", "baudrate": 9600},
            }
        ],
        "steps": [],
        "teardown": [
            {"id": "disconnect", "action": "serial.disconnect", "args": {"conn": "${conn}"}},
        ],
    }
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    report_dir = tmp_path / "report"
    ExecCommand.run(file=str(path), options={"report": str(report_dir)})

    read = ExecCommand.read_report(str(report_dir), format="compact")
    assert read["ok"] is True
    assert read["compact"]["purpose"] == "读报告"
    assert read["execution_report_md"]
