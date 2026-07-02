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
    assert (report_dir / "summary.json").exists()
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


def test_run_dry_run_translates_target_channels(tmp_path):
    plan = _write_plan(
        tmp_path / "lab_dry.yaml",
        {
            "version": 1,
            "name": "lab_dry",
            "target_profiles": {
                "cco_profile": {
                    "channels": {
                        "data": {
                            "conn": "cco_data",
                            "port": "mock://loop",
                            "role": "protocol_uart",
                            "protocol": "csg",
                            "required": True,
                        }
                    }
                },
                "sta_profile": {
                    "channels": {
                        "data": {
                            "conn": "sta_data",
                            "port": "virtual://sta",
                            "role": "protocol_uart",
                            "protocol": "dlt645",
                            "required": True,
                        }
                    }
                },
            },
            "targets": {
                "cco": {"profile": "cco_profile"},
                "sta1": {"profile": "sta_profile"},
            },
            "setup": [
                {
                    "id": "connect_cco",
                    "action": "serial.connect",
                    "args": {"target": "cco", "channel": "data", "baudrate": 9600},
                },
                {
                    "id": "connect_sta",
                    "action": "serial.connect",
                    "args": {"target": "sta1", "channel": "data", "baudrate": 2400},
                },
            ],
            "steps": [
                {
                    "id": "send_cco",
                    "action": "send",
                    "args": {"target": "cco", "channel": "data", "hex": "01 02", "timeout": 0},
                },
                {
                    "id": "scoped_rule",
                    "action": "auto_rule.add",
                    "args": {
                        "id": "lab_scope_rule",
                        "scope": {"target": "cco", "channel": "data"},
                        "match": "01 02",
                        "then": {"command": "send", "args": {"hex": "03 04"}},
                    },
                },
            ],
        },
    )

    report_dir = tmp_path / "lab_report"
    result = exec_cmd("run", {"file": str(plan), "dry-run": True, "report": str(report_dir)})

    assert result["status"] == "success"
    assert result["data"]["status"] == "success"
    resolved = yaml.safe_load((report_dir / "resolved_plan.yaml").read_text(encoding="utf-8"))
    assert resolved["setup"][0]["args"]["name"] == "cco_data"
    assert resolved["setup"][0]["args"]["port"] == "mock://loop"
    assert resolved["setup"][1]["args"]["name"] == "sta_data"
    assert resolved["steps"][0]["args"]["to"] == "cco_data"
    assert resolved["steps"][0]["args"]["proto"] == "csg"
    assert resolved["steps"][1]["args"]["source"] == "serial:cco_data"
    summary = yaml.safe_load((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["lab"]["lease"]["targets"]["cco"]["channels"] == ["data"]
    assert summary["lab"]["lease"]["targets"]["sta1"]["channels"] == ["data"]


def test_run_missing_optional_debug_only_fails_when_referenced(tmp_path):
    ok_plan = _write_plan(
        tmp_path / "data_only.yaml",
        {
            "version": 1,
            "name": "data_only",
            "targets": {
                "meter": {
                    "channels": {
                        "data": {
                            "conn": "meter_data",
                            "port": "mock://loop",
                            "role": "protocol_uart",
                            "protocol": "dlt645",
                            "required": True,
                        }
                    }
                }
            },
            "steps": [
                {"id": "noop", "action": "set_var", "args": {"name": "ok", "value": True}}
            ],
        },
    )
    ok = exec_cmd("run", {"file": str(ok_plan), "report": str(tmp_path / "ok_report")})
    assert ok["data"]["status"] == "success"

    bad_plan = _write_plan(
        tmp_path / "missing_debug.yaml",
        {
            "version": 1,
            "name": "missing_debug",
            "targets": {
                "cco": {
                    "channels": {
                        "data": {
                            "conn": "cco_data_missing_debug",
                            "port": "mock://loop",
                            "role": "protocol_uart",
                            "required": True,
                        }
                    }
                }
            },
            "steps": [
                {
                    "id": "wait_debug",
                    "action": "wait_log",
                    "args": {
                        "target": "cco",
                        "channel": "debug",
                        "expect": {"contains": "ready"},
                        "timeout_ms": 1,
                    },
                }
            ],
        },
    )
    bad = exec_cmd("run", {"file": str(bad_plan), "report": str(tmp_path / "bad_report")})
    assert bad["status"] == "success"
    assert bad["data"]["status"] == "fail"
    assert "target cco has no channel debug" in bad["data"]["error"]


def test_run_wait_log_writes_debug_report_by_channel(tmp_path):
    plan = _write_plan(
        tmp_path / "debug_log.yaml",
        {
            "version": 1,
            "name": "debug_log",
            "targets": {
                "cco": {
                    "channels": {
                        "debug": {
                            "conn": "debug_log_conn",
                            "port": "mock://loop",
                            "role": "debug_uart",
                            "required": False,
                        }
                    }
                }
            },
            "setup": [
                {
                    "id": "connect_debug",
                    "action": "serial.connect",
                    "args": {"target": "cco", "channel": "debug"},
                }
            ],
            "steps": [
                {
                    "id": "print_ready",
                    "action": "send",
                    "args": {
                        "target": "cco",
                        "channel": "debug",
                        "hex": "66 69 72 6D 77 61 72 65 20 72 65 61 64 79",
                        "timeout": 0,
                    },
                },
                {
                    "id": "wait_ready",
                    "action": "wait_log",
                    "args": {
                        "target": "cco",
                        "channel": "debug",
                        "expect": {"contains": "firmware ready"},
                        "timeout_ms": 1000,
                    },
                },
            ],
            "teardown": [
                {
                    "id": "close_debug",
                    "action": "serial.disconnect",
                    "args": {"target": "cco", "channel": "debug"},
                }
            ],
        },
    )

    report_dir = tmp_path / "debug_report"
    result = exec_cmd("run", {"file": str(plan), "report": str(report_dir), "timeout": 5000})

    assert result["status"] == "success"
    assert result["data"]["status"] == "success"
    debug_log = (report_dir / "debug.log").read_text(encoding="utf-8")
    assert "firmware ready" in debug_log
    assert "cco.debug" in debug_log
    data_frames = (report_dir / "data_frames.log").read_text(encoding="utf-8")
    assert "firmware ready" not in data_frames


def test_run_auto_rule_scope_matches_only_target_channel(tmp_path):
    from console.handlers import auto_rule as auto_rule_mod

    auto_rule_mod._rules.clear()
    auto_rule_mod._rule_history.clear()
    plan = _write_plan(
        tmp_path / "rule_scope.yaml",
        {
            "version": 1,
            "name": "rule_scope",
            "targets": {
                "cco": {
                    "channels": {
                        "data": {
                            "conn": "scope_cco_data",
                            "port": "mock://loop",
                            "role": "protocol_uart",
                            "required": True,
                        }
                    }
                },
                "sta1": {
                    "channels": {
                        "data": {
                            "conn": "scope_sta_data",
                            "port": "mock://loop",
                            "role": "protocol_uart",
                            "required": True,
                        }
                    }
                },
            },
            "setup": [
                {"id": "connect_cco", "action": "serial.connect", "args": {"target": "cco", "channel": "data"}},
                {"id": "connect_sta", "action": "serial.connect", "args": {"target": "sta1", "channel": "data"}},
                {
                    "id": "add_rule",
                    "action": "auto_rule.add",
                    "args": {
                        "id": "scope_rule",
                        "scope": {"target": "cco", "channel": "data"},
                        "match": "AA",
                        "then": {"command": "print", "args": {"text": "hit"}},
                    },
                },
            ],
            "steps": [
                {
                    "id": "send_sta",
                    "action": "send",
                    "args": {"target": "sta1", "channel": "data", "hex": "68 AA 16", "timeout": 0},
                },
                {
                    "id": "send_cco",
                    "action": "send",
                    "args": {"target": "cco", "channel": "data", "hex": "68 AA 16", "timeout": 0},
                },
                {"id": "let_monitor_run", "action": "sleep", "args": {"ms": 50}},
            ],
            "teardown": [
                {"id": "remove_rule", "action": "auto_rule.remove", "args": {"id": "scope_rule"}},
                {"id": "close_cco", "action": "serial.disconnect", "args": {"target": "cco", "channel": "data"}},
                {"id": "close_sta", "action": "serial.disconnect", "args": {"target": "sta1", "channel": "data"}},
            ],
        },
    )

    result = exec_cmd("run", {"file": str(plan), "report": str(tmp_path / "scope_report")})

    assert result["status"] == "success"
    assert result["data"]["status"] == "success"
    hits = [item for item in auto_rule_mod._rule_history if item.get("rule_id") == "scope_rule"]
    assert len(hits) == 1
