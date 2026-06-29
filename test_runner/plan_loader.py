from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class PlanError(ValueError):
    pass


def load_plan(path: str | Path, *, vars: dict[str, Any] | None = None) -> dict[str, Any]:
    plan_path = Path(path)
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlanError(f"plan file not found: {plan_path}") from None
    except Exception as exc:
        raise PlanError(f"failed to load plan: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan must be a YAML object")
    from test_runner.plan_compose import compose_plan

    data = compose_plan(data, plan_path=plan_path, vars=vars)
    _validate_raise(data)
    return data


def load_plan_dict(plan: dict[str, Any], *, vars: dict[str, Any] | None = None) -> dict[str, Any]:
    data = deepcopy(plan)
    from test_runner.plan_compose import compose_plan

    data = compose_plan(data, vars=vars)
    _validate_raise(data)
    return data


def _validate_raise(plan: dict[str, Any]) -> None:
    from test_runner.plan_validator import validate_plan_raise

    validate_plan_raise(plan)
