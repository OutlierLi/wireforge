"""配对串口 TestPlan YAML 生成与 exec_test 冒烟。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from test_runner.exec_command import ExecCommand, ExecOptions

SINGLE_PAIR = _project_root / "database" / "runs" / "csg_pair_serial_afn01_init_archive.yaml"
TEMPLATE = _project_root / "database" / "templates" / "pair_serial_test_plan.yaml"


@pytest.fixture(scope="module")
def ensure_single_pair_yaml():
    if not SINGLE_PAIR.exists():
        from scripts.generate_pair_serial_plans import generate

        generate(proto_key="csg", pair_id="afn01_init_archive")
    return SINGLE_PAIR


def test_pair_serial_template_validate():
    from test_runner.plan_loader import load_plan
    from test_runner.plan_validator import validate_plan

    plan = load_plan(str(TEMPLATE))
    result = validate_plan(plan)
    assert result["ok"] is True, result.get("errors")


def test_generated_pair_serial_mock_exec(ensure_single_pair_yaml):
    result = ExecCommand.run(
        file=str(ensure_single_pair_yaml),
        options=ExecOptions(vars={"port": "mock://auto"}),
    )
    assert result.get("ok") is True, result.get("error")
    assert result.get("report_dir")


def test_csg_add_task_multi_wait_mock_exec():
    plan_path = _project_root / "database" / "runs" / "csg_pair_serial_afn02_add_task.yaml"
    if not plan_path.exists():
        from scripts.generate_pair_serial_plans import generate

        generate(proto_key="csg", pair_id="afn02_add_task")

    result = ExecCommand.run(
        file=str(plan_path),
        options=ExecOptions(vars={"port": "mock://auto", "wait_timeout_ms": 8000}),
    )
    assert result.get("ok") is True, result.get("error")
