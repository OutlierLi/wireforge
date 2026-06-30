from __future__ import annotations

import yaml

from test_runner.build_schema_check import (
    check_build_step,
    check_plan_builds,
    collect_build_steps,
)
from test_runner.error_codes import PLAN_BUILD_SCHEMA_MISMATCH
from test_runner.run_command import RunCommand


def _add_slave_build(**extra) -> dict:
    args = {
        "proto": "csg",
        "afn": "04",
        "di": "E8020402",
        "dir": "downlink",
        "slave_count": 1,
        "slave_addrs": ["000000000001"],
    }
    args.update(extra)
    return args


def test_collect_build_steps_in_loop():
    plan = {
        "version": 1,
        "name": "nested",
        "steps": [
            {
                "id": "loop_add",
                "action": "loop",
                "args": {"count": 2},
                "steps": [
                    {
                        "id": "build_batch",
                        "action": "build",
                        "args": _add_slave_build(),
                    }
                ],
            }
        ],
    }
    refs = collect_build_steps(plan)
    assert len(refs) == 1
    assert refs[0].step_id == "loop_add.build_batch"


def test_add_slave_build_ok():
    result = check_build_step(_add_slave_build(), scope={}, step_id="ok_step")
    assert result.status == "ok"
    assert not result.unknown_fields
    assert not result.missing_required


def test_unknown_field_mismatch():
    result = check_build_step(
        _add_slave_build(slave_address="000000000001"),
        scope={},
        step_id="bad_field",
    )
    assert result.status == "mismatch"
    assert "slave_address" in result.unknown_fields


def test_missing_required_mismatch():
    result = check_build_step(
        {
            "proto": "csg",
            "afn": "04",
            "di": "E8020402",
            "dir": "downlink",
            "slave_count": 1,
        },
        scope={},
        step_id="missing_nodes",
    )
    assert result.status == "mismatch"
    assert "slave_addrs" in result.missing_required


def test_incomplete_locator_skipped():
    result = check_build_step(
        {"proto": "csg", "afn": "02", "dir": "downlink", "node_count": 1},
        scope={},
        step_id="no_di",
    )
    assert result.status == "skipped_incomplete_locator"


def test_dynamic_args_skipped_on_validate():
    plan = {
        "version": 1,
        "name": "dynamic",
        "steps": [
            {
                "id": "build_dynamic",
                "action": "build",
                "args": {
                    "proto": "${proto}",
                    "afn": "04",
                    "di": "E8020402",
                    "dir": "downlink",
                    "slave_count": 1,
                    "slave_addrs": "${batch.addrs}",
                },
            }
        ],
    }
    result = check_plan_builds(plan, vars={})
    check = result["build_checks"][0]
    assert check["status"] == "skipped_dynamic"
    assert result["ok"] is True


def test_dynamic_resolved_on_dry_run(tmp_path):
    plan = {
        "version": 1,
        "name": "dynamic_resolved",
        "vars": {
            "proto": "csg",
            "batch": {"addrs": ["000000000001", "000000000002"]},
        },
        "steps": [
            {
                "id": "build_dynamic",
                "action": "build",
                "args": {
                    "proto": "${proto}",
                    "afn": "04",
                    "di": "E8020402",
                    "dir": "downlink",
                    "slave_count": 2,
                    "slave_addrs": "${batch.addrs}",
                },
            }
        ],
    }
    path = tmp_path / "dynamic.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    dry = RunCommand.dry_run(file=str(path))
    assert dry["ok"] is True
    checks = dry.get("build_checks") or []
    assert any(c["step_id"] == "build_dynamic" and c["status"] == "ok" for c in checks)


def test_validate_returns_build_schema_mismatch():
    plan = {
        "version": 1,
        "name": "bad_build",
        "steps": [
            {
                "id": "build_bad",
                "action": "build",
                "args": _add_slave_build(slave_address="x"),
            }
        ],
    }
    result = RunCommand.validate(plan=plan)
    assert result["ok"] is False
    assert result["errors"][0]["code"] == PLAN_BUILD_SCHEMA_MISMATCH
    assert result["errors"][0]["step_id"] == "build_bad"
    assert "build_checks" in result


def test_run_blocks_on_build_mismatch(tmp_path):
    plan = {
        "version": 1,
        "name": "blocked",
        "steps": [
            {
                "id": "build_bad",
                "action": "build",
                "args": _add_slave_build(slave_address="x"),
            }
        ],
    }
    path = tmp_path / "blocked.yaml"
    path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")
    result = RunCommand.run(
        file=str(path),
        options={"report": str(tmp_path / "report"), "dry_run": True},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == PLAN_BUILD_SCHEMA_MISMATCH


def test_schema_includes_build_field_types_and_workflow():
    schema = RunCommand.schema()
    assert "build_field_types" in schema
    assert isinstance(schema["build_field_types"], list)
    assert any(entry["type"] == "array" for entry in schema["build_field_types"])
    assert "workflow" in schema
    assert "test.dry_run" in " ".join(schema["workflow"]["order"])
