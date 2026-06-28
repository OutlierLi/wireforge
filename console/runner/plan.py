from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PlanError(ValueError):
    pass


def load_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path)
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlanError(f"plan file not found: {plan_path}") from None
    except Exception as exc:
        raise PlanError(f"failed to load plan: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan must be a YAML object")
    validate_plan(data)
    return data


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("version") != 1:
        raise PlanError("plan.version must be 1")
    if not plan.get("name"):
        raise PlanError("plan.name is required")
    if "steps" not in plan or not isinstance(plan["steps"], list):
        raise PlanError("plan.steps must be a list")
    for section in ("setup", "steps", "teardown"):
        steps = plan.get(section, [])
        if steps is None:
            continue
        if not isinstance(steps, list):
            raise PlanError(f"plan.{section} must be a list")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise PlanError(f"{section}[{index}] must be an object")
            if not step.get("action"):
                raise PlanError(f"{section}[{index}].action is required")
            if not step.get("id"):
                step["id"] = f"{section}_{index + 1}"

