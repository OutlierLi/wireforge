from __future__ import annotations

import io
import json
from pathlib import Path

import yaml

from mcp_servers.test.server import TOOLS, call_tool, handle_message, serve
from test_runner.error_codes import PLAN_SCHEMA_INVALID, PLAN_ACTION_UNKNOWN
from test_runner.run_command import RunCommand, RunOptions


def _write_plan(path: Path, plan: dict) -> Path:
    path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_tools_list_includes_five_tools():
    response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {t["name"] for t in TOOLS}
    assert len(names) == 5


def test_test_schema_returns_plan_schema():
    result = call_tool("test.schema", {})
    assert result["version"] == 1
    assert "build" in result["supported_actions"]
    assert result["test_plan_schema"]["required"] == ["version", "name", "steps"]
    assert result["template"] == "database/templates/test_plan_mock_auto.yaml"
    assert "prerequisite" in result
    assert result["conventions"]["default_port"] == "mock://auto"
    assert "loop" in result["supported_actions"]
    assert "if" in result["supported_actions"]
    assert "expr" in result["supported_actions"]


def test_test_validate_rejects_invalid_plan():
    result = call_tool("test.validate", {"plan": {"version": 2, "name": "bad"}})
    assert result["ok"] is False
    assert result["errors"][0]["code"] == PLAN_SCHEMA_INVALID


def test_test_validate_rejects_unknown_action():
    result = call_tool("test.validate", {
        "plan": {
            "version": 1,
            "name": "bad_action",
            "steps": [{"id": "x", "action": "not_real"}],
        }
    })
    assert result["ok"] is False
    assert any(e["code"] == PLAN_ACTION_UNKNOWN for e in result["errors"])


def test_test_dry_run_resolves_vars(tmp_path):
    plan = _write_plan(tmp_path / "plan.yaml", {
        "version": 1,
        "name": "dry",
        "vars": {"port": "mock://a"},
        "steps": [{"id": "s1", "action": "set_var", "args": {"name": "x", "value": "${port}"}}],
    })
    result = call_tool("test.dry_run", {"file": str(plan), "vars": {"port": "mock://b"}})
    assert result["ok"] is True
    assert result["resolved_plan"]["vars"]["port"] == "mock://b"


def test_test_run_dry_run_writes_report(tmp_path):
    plan = _write_plan(tmp_path / "plan.yaml", {
        "version": 1,
        "name": "mcp_dry",
        "steps": [{"id": "sleep1", "action": "sleep", "args": {"ms": 1}}],
    })
    result = call_tool("test.run", {
        "file": str(plan),
        "options": {"dry_run": True, "report": str(tmp_path / "report")},
    })
    assert result["ok"] is True
    report_dir = Path(result["report_dir"])
    assert (report_dir / "resolved_plan.yaml").exists()
    assert (report_dir / "summary.json").exists()
    assert (report_dir / "mcp_result.json").exists()


def test_test_read_report(tmp_path):
    plan = _write_plan(tmp_path / "plan.yaml", {
        "version": 1,
        "name": "read_report",
        "steps": [{"id": "s1", "action": "sleep", "args": {"ms": 1}}],
    })
    run_result = RunCommand.run(
        file=str(plan),
        options=RunOptions(dry_run=True, report=str(tmp_path / "report")),
    )
    read = call_tool("test.read_report", {"report_dir": run_result["report_dir"]})
    assert read["ok"] is True
    assert read["summary"]["status"] == "success"


def test_stdio_serve_json_lines():
    stdin = io.BytesIO(json.dumps({
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/list",
        "params": {},
    }).encode("utf-8") + b"\n")
    stdout = io.BytesIO()
    serve(stdin, stdout)
    response = json.loads(stdout.getvalue().decode("utf-8").strip())
    assert response["id"] == 9
    assert len(response["result"]["tools"]) == 5


def test_run_command_validate_inline():
    result = RunCommand.validate(plan={"version": 1, "name": "ok", "steps": []})
    assert result["ok"] is True
