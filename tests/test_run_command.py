from __future__ import annotations

from pathlib import Path

import yaml

from console.api import exec_cmd, exec_text


def _write_plan(path: Path, plan: dict) -> Path:
    path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_run_dry_run_writes_report_and_resolves_vars(tmp_path):
    plan = _write_plan(
        tmp_path / "plan.yaml",
        {
            "version": 1,
            "name": "dry_run_plan",
            "vars": {"conn": "cco", "port": "mock://loop"},
            "setup": [
                {
                    "id": "connect",
                    "action": "serial.connect",
                    "args": {"conn": "${conn}", "port": "${port}", "baudrate": 9600},
                }
            ],
            "steps": [
                {
                    "id": "remember",
                    "action": "set_var",
                    "args": {"name": "saved_port", "value": "${port}"},
                }
            ],
            "teardown": [
                {"id": "disconnect", "action": "serial.disconnect", "args": {"conn": "${conn}"}}
            ],
        },
    )
    report_dir = tmp_path / "report"

    result = exec_cmd(
        "run",
        {
            "file": str(plan),
            "dry-run": True,
            "var": ["port=mock://override", "conn=sta"],
            "report": str(report_dir),
        },
    )

    assert result["status"] == "success"
    data = result["data"]
    assert data["status"] == "success"
    assert Path(data["report"]) == report_dir
    assert (report_dir / "plan.yaml").exists()
    assert (report_dir / "resolved_plan.yaml").exists()
    assert (report_dir / "report.json").exists()
    assert (report_dir / "timeline.log").exists()
    resolved = yaml.safe_load((report_dir / "resolved_plan.yaml").read_text(encoding="utf-8"))
    assert resolved["setup"][0]["args"]["name"] == "sta"
    assert resolved["setup"][0]["args"]["port"] == "mock://override"


def test_run_executes_build_step_and_saves_alias(tmp_path):
    plan = _write_plan(
        tmp_path / "build_plan.yaml",
        {
            "version": 1,
            "name": "build_plan",
            "steps": [
                {
                    "id": "make_frame",
                    "action": "build",
                    "save_as": "built",
                    "args": {
                        "proto": "csg",
                        "afn": "0x03",
                        "dir": "downlink",
                        "di": "E8000301",
                    },
                },
                {
                    "id": "check_alias",
                    "action": "assert",
                    "args": {
                        "expect": {
                            "built.frame_hex": "68 0C 00 40 03 01 01 03 00 E8 30 16"
                        }
                    },
                },
            ],
        },
    )

    result = exec_cmd("run", {"file": str(plan), "report": str(tmp_path / "report")})

    assert result["status"] == "success"
    data = result["data"]
    assert data["status"] == "success"
    assert [step["status"] for step in data["steps"]] == ["ok", "ok"]


def test_run_repeated_var_cli_parsing(tmp_path):
    plan = _write_plan(
        tmp_path / "vars.yaml",
        {
            "version": 1,
            "name": "vars_plan",
            "vars": {"a": "1", "b": "2"},
            "steps": [
                {
                    "id": "check",
                    "action": "assert",
                    "args": {"expect": {"a": "x", "b": "y"}},
                }
            ],
        },
    )

    result = exec_text(f"/run --file {plan} --var a=x --var b=y --report {tmp_path / 'report'}")

    assert result["status"] == "success"
    assert result["data"]["status"] == "success"


def test_run_stops_on_failure_but_runs_teardown(tmp_path):
    plan = _write_plan(
        tmp_path / "fail.yaml",
        {
            "version": 1,
            "name": "fail_plan",
            "steps": [
                {"id": "bad", "action": "assert", "args": {"expect": {"missing": "value"}}}
            ],
            "teardown": [
                {"id": "cleanup", "action": "set_var", "args": {"name": "cleaned", "value": True}}
            ],
        },
    )

    result = exec_cmd("run", {"file": str(plan), "report": str(tmp_path / "report")})

    assert result["status"] == "success"
    assert result["data"]["status"] == "fail"
    assert [step["id"] for step in result["data"]["steps"]] == ["bad", "cleanup"]
    assert result["data"]["steps"][0]["status"] == "fail"
    assert result["data"]["steps"][1]["status"] == "ok"
