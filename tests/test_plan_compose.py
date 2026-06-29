from __future__ import annotations

from pathlib import Path

import yaml

from test_runner.conditions import evaluate_when
from test_runner.plan_compose import compose_plan
from test_runner.plan_loader import load_plan_dict
from test_runner.run_command import RunCommand, RunOptions


def test_when_string_equality():
    scope = {"port": "mock://auto", "conn": "cco"}
    assert evaluate_when("port == mock://auto", scope)
    assert not evaluate_when("port == /dev/ttyUSB0", scope)
    assert evaluate_when("not port == /dev/ttyUSB0", scope)


def test_include_skipped_when_false(tmp_path):
    fragment = tmp_path / "frag.yaml"
    fragment.write_text(
        yaml.safe_dump({"steps": [{"id": "x", "action": "set_var", "args": {"name": "a", "value": 1}}]}),
        encoding="utf-8",
    )
    plan = {
        "version": 1,
        "name": "inc",
        "vars": {"port": "COM3"},
        "steps": [
            {
                "id": "inc",
                "action": "include",
                "args": {"file": str(fragment), "when": "port == mock://auto"},
            }
        ],
    }
    out = compose_plan(plan)
    assert out["steps"] == []


def test_include_expands_fragment(tmp_path):
    fragment = tmp_path / "frag.yaml"
    fragment.write_text(
        yaml.safe_dump(
            {
                "steps": [
                    {"id": "inner", "action": "set_var", "args": {"name": "flag", "value": "ok"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "version": 1,
        "name": "inc",
        "steps": [{"id": "inc", "action": "include", "args": {"file": str(fragment)}}],
    }
    out = compose_plan(plan)
    assert len(out["steps"]) == 1
    assert out["steps"][0]["id"] == "inner"


def test_parametrize_over_expands():
    plan = {
        "version": 1,
        "name": "param",
        "vars": {"items": [{"n": "a"}, {"n": "b"}]},
        "steps": [
            {
                "id": "cases",
                "action": "parametrize",
                "args": {"over": "${items}", "as": "item"},
                "steps": [
                    {
                        "id": "save",
                        "action": "set_var",
                        "args": {"name": "last", "value": "${item.n}"},
                    }
                ],
            }
        ],
    }
    out = compose_plan(plan)
    ids = [s["id"] for s in out["steps"]]
    assert "cases_0.__bind_item" in ids
    assert "cases_0.save" in ids
    assert "cases_1.save" in ids
    assert not any(s.get("action") == "parametrize" for s in out["steps"])


def test_parametrize_count_with_include(tmp_path):
    frag = tmp_path / "batch.yaml"
    frag.write_text(
        yaml.safe_dump(
            {
                "steps": [
                    {
                        "id": "calc",
                        "action": "expr",
                        "args": {"name": "off", "expr": "${query_idx} * 32"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "version": 1,
        "name": "param_inc",
        "steps": [
            {
                "id": "batches",
                "action": "parametrize",
                "args": {"count": 2, "index_as": "query_idx"},
                "steps": [
                    {"action": "include", "args": {"file": str(frag)}},
                ],
            }
        ],
    }
    out = compose_plan(plan)
    calc_steps = [s for s in out["steps"] if s.get("id", "").endswith(".calc")]
    assert len(calc_steps) == 2


def test_load_plan_dict_compose_and_validate():
    plan = {
        "version": 1,
        "name": "ok",
        "steps": [
            {
                "id": "cases",
                "action": "parametrize",
                "args": {"count": 1},
                "steps": [
                    {"id": "noop", "action": "set_var", "args": {"name": "x", "value": 1}},
                ],
            }
        ],
    }
    loaded = load_plan_dict(plan)
    assert loaded["steps"][0]["action"] == "set_var"


def test_add_slave_compose_has_no_loop_actions():
    root = Path(__file__).resolve().parent.parent
    raw = yaml.safe_load(
        (root / "database/runs/add_slave_nodes_loop.yaml").read_text(encoding="utf-8")
    )
    composed = compose_plan(raw, plan_path=root / "database/runs/add_slave_nodes_loop.yaml")
    actions = {s.get("action") for s in composed.get("steps", [])}
    assert "loop" not in actions
    assert "parametrize" not in actions
    assert "include" not in actions
    assert any("add_slave_batches_0" in s.get("id", "") for s in composed["steps"])


def test_add_slave_mock_run(tmp_path):
    result = RunCommand.run(
        file="database/runs/add_slave_nodes_loop.yaml",
        options=RunOptions(
            report=str(tmp_path / "report"),
            timeout_ms=600000,
            vars={"port": "mock://auto"},
        ),
    )
    assert result["ok"] is True
