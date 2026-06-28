from __future__ import annotations

from copy import deepcopy
from typing import Any

from test_runner.error_codes import KNOWN_ACTIONS, PLAN_ACTION_UNKNOWN, PLAN_SCHEMA_INVALID, RunError


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    _collect_errors(plan, errors)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "errors": []}


def validate_plan_raise(plan: dict[str, Any]) -> None:
    result = validate_plan(deepcopy(plan))
    if not result["ok"]:
        messages = "; ".join(e["message"] for e in result["errors"])
        from test_runner.plan_loader import PlanError

        raise PlanError(messages)


def _collect_errors(plan: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    if plan.get("version") != 1:
        errors.append(_err(PLAN_SCHEMA_INVALID, "plan.version must be 1"))
    if not plan.get("name"):
        errors.append(_err(PLAN_SCHEMA_INVALID, "plan.name is required"))
    if "steps" not in plan or not isinstance(plan["steps"], list):
        errors.append(_err(PLAN_SCHEMA_INVALID, "plan.steps must be a list"))
    for section in ("setup", "steps", "teardown"):
        steps = plan.get(section, [])
        if steps is None:
            continue
        if not isinstance(steps, list):
            errors.append(_err(PLAN_SCHEMA_INVALID, f"plan.{section} must be a list"))
            continue
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(_err(PLAN_SCHEMA_INVALID, f"{section}[{index}] must be an object"))
                continue
            if not step.get("action"):
                errors.append(_err(PLAN_SCHEMA_INVALID, f"{section}[{index}].action is required"))
                continue
            action = str(step["action"])
            if action not in KNOWN_ACTIONS:
                errors.append(_err(
                    PLAN_ACTION_UNKNOWN,
                    f"{section}[{index}].action '{action}' is not supported",
                    step_id=str(step.get("id") or f"{section}_{index + 1}"),
                ))
            if not step.get("id"):
                step["id"] = f"{section}_{index + 1}"


def _err(code: str, message: str, step_id: str = "") -> dict[str, Any]:
    err = RunError(code, message, step_id=step_id)
    return err.to_dict()
