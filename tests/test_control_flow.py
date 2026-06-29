from __future__ import annotations

from pathlib import Path

import yaml

from test_runner.conditions import evaluate_when
from test_runner.run_command import RunCommand, RunOptions
from test_runner.variables import get_path


def test_loop_count(tmp_path):
    plan = {
        "version": 1,
        "name": "loop_count",
        "steps": [
            {
                "id": "loop_n",
                "action": "loop",
                "args": {"count": 3, "index_as": "i"},
                "steps": [
                    {
                        "id": "save",
                        "action": "set_var",
                        "args": {"name": "last_i", "value": "${i}"},
                    }
                ],
            },
            {
                "id": "check",
                "action": "assert",
                "args": {"expect": {"last_i": 2}},
            },
        ],
    }
    path = tmp_path / "loop_count.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report")))
    assert result["ok"] is True


def test_loop_over_struct(tmp_path):
    plan = {
        "version": 1,
        "name": "loop_over",
        "vars": {
            "items": [
                {"name": "a", "value": 1},
                {"name": "b", "value": 2},
            ]
        },
        "steps": [
            {
                "id": "loop_items",
                "action": "loop",
                "args": {"over": "${items}", "as": "item"},
                "steps": [
                    {
                        "id": "save_name",
                        "action": "set_var",
                        "args": {"name": "last_name", "value": "${item.name}"},
                    }
                ],
            },
            {
                "id": "check",
                "action": "assert",
                "args": {"expect": {"last_name": "b"}},
            },
        ],
    }
    path = tmp_path / "loop_over.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report2")))
    assert result["ok"] is True


def test_if_else_branch(tmp_path):
    plan = {
        "version": 1,
        "name": "if_else",
        "vars": {"mode": "real"},
        "steps": [
            {
                "id": "choose",
                "action": "if",
                "args": {"when": {"eq": {"mode": "mock"}}},
                "steps": [
                    {"id": "then_step", "action": "set_var", "args": {"name": "branch", "value": "mock"}},
                ],
                "else_steps": [
                    {"id": "else_step", "action": "set_var", "args": {"name": "branch", "value": "real"}},
                ],
            },
            {"id": "check", "action": "assert", "args": {"expect": {"branch": "real"}}},
        ],
    }
    path = tmp_path / "if_else.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report3")))
    assert result["ok"] is True


def test_evaluate_when_all_and_not():
    scope = {"port": "mock://auto", "flag": "1"}
    assert evaluate_when({"eq": {"port": "mock://auto"}}, scope)
    assert evaluate_when({"not": {"eq": {"port": "COM3"}}}, scope)
    assert evaluate_when({"all": [{"eq": {"port": "mock://auto"}}, {"not": {"eq": {"flag": "0"}}}]}, scope)


def test_loop_batch_demo_file():
    result = RunCommand.run(
        file="database/runs/loop_batch_demo.yaml",
        options=RunOptions(report="log/run_reports/loop_batch_demo_verify", timeout_ms=60000),
    )
    assert result["ok"] is True


def test_dry_run_port_override_with_loop():
    result = RunCommand.dry_run(
        file="database/runs/loop_batch_demo.yaml",
        vars={"port": "/dev/ttyUSB0"},
    )
    assert result["ok"] is True
    assert result["warnings"]
    connect = result["resolved_plan"]["setup"][0]["args"]
    assert connect["port"] == "/dev/ttyUSB0"


def test_validate_loop_requires_over_or_count():
    result = RunCommand.validate(plan={
        "version": 1,
        "name": "bad_loop",
        "steps": [{"id": "x", "action": "loop", "args": {}, "steps": []}],
    })
    assert result["ok"] is False


def test_get_path_array_in_loop_scope():
    scope = {"batch": {"addrs": ["aa", "bb"]}}
    assert get_path(scope, "batch.addrs.1") == "bb"


def test_expr_action(tmp_path):
    plan = {
        "version": 1,
        "name": "expr_action",
        "vars": {"qi": 2},
        "steps": [
            {"id": "calc", "action": "expr", "args": {"name": "start_index", "expr": "qi * 32"}},
            {"id": "check", "action": "assert", "args": {"expect": {"start_index": 64}}},
        ],
    }
    path = tmp_path / "expr_action.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report_expr")))
    assert result["ok"] is True


def test_loop_count_default_qi_index(tmp_path):
    """count loop without index_as injects qi/i for batch arithmetic."""
    plan = {
        "version": 1,
        "name": "loop_qi_default",
        "steps": [
            {
                "id": "loop",
                "action": "loop",
                "args": {"count": 3},
                "steps": [
                    {
                        "id": "calc",
                        "action": "expr",
                        "args": {"name": "batch_offset", "expr": "qi * 32"},
                    },
                ],
            },
            {
                "id": "check",
                "action": "assert",
                "args": {"expect": {"batch_offset": 64}},
            },
        ],
    }
    path = tmp_path / "loop_qi_default.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report_qi")))
    assert result["ok"] is True


def test_dry_run_count_loop_resolves_qi_expr():
    plan = {
        "version": 1,
        "name": "dry_qi",
        "steps": [
            {
                "id": "loop_batches",
                "action": "loop",
                "args": {"count": 2},
                "steps": [
                    {
                        "id": "calc",
                        "action": "expr",
                        "args": {"name": "off", "expr": "${qi * 32}"},
                    },
                ],
            },
        ],
    }
    result = RunCommand.dry_run(plan=plan)
    assert result["ok"] is True
    preview = result["resolved_plan"]["steps"][0]["loop_preview"]
    assert preview["steps"][0]["args"]["expr"] == 0
    assert preview["steps"][1]["args"]["expr"] == 32


def test_loop_explicit_index_as_disables_qi_alias(tmp_path):
    plan = {
        "version": 1,
        "name": "loop_no_qi",
        "steps": [
            {
                "id": "loop",
                "action": "loop",
                "args": {"count": 2, "index_as": "batch_idx"},
                "steps": [
                    {
                        "id": "calc",
                        "action": "expr",
                        "args": {"name": "off", "expr": "batch_idx * 32"},
                    },
                ],
            },
            {"id": "check", "action": "assert", "args": {"expect": {"off": 32}}},
        ],
    }
    path = tmp_path / "loop_no_qi.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report_no_qi")))
    assert result["ok"] is True


def test_loop_iteration_scope_isolated(tmp_path):
    plan = {
        "version": 1,
        "name": "loop_scope",
        "vars": {"outer_marker": "keep"},
        "steps": [
            {
                "id": "loop",
                "action": "loop",
                "args": {"count": 3, "index_as": "i"},
                "steps": [
                    {"id": "set_round", "action": "set_var", "args": {"name": "round_val", "value": "${i}"}},
                    {"id": "set_temp", "action": "set_var", "args": {"name": "temp_only", "value": "${i * 10}"}},
                ],
            },
            {"id": "check_last", "action": "assert", "args": {"expect": {"round_val": 2, "temp_only": 20}}},
            {"id": "check_outer", "action": "assert", "args": {"expect": {"outer_marker": "keep"}}},
        ],
    }
    path = tmp_path / "loop_scope.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(file=str(path), options=RunOptions(report=str(tmp_path / "report_scope")))
    assert result["ok"] is True


def test_dry_run_loop_preview():
    result = RunCommand.dry_run(file="database/runs/loop_batch_demo.yaml")
    assert result["ok"] is True
    count_loop = next(
        step for step in result["resolved_plan"]["steps"]
        if step.get("id") == "loop_count_demo"
    )
    preview = count_loop["loop_preview"]
    assert preview["iterations"] == 3
    assert preview["expanded"] == 3
    assert preview["steps"][0]["args"]["value"] == 0
    assert preview["steps"][-1]["args"]["value"] == 2

    batch_loop = next(
        step for step in result["resolved_plan"]["steps"]
        if step.get("id") == "loop_batches"
    )
    batch_preview = batch_loop["loop_preview"]
    assert batch_preview["iterations"] == 2
    assert batch_preview["steps"][0]["args"]["value"] == "batch_a"

