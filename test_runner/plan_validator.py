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
        _validate_steps(steps, section, errors)


def _validate_steps(steps: list[Any], section: str, errors: list[dict[str, Any]]) -> None:
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

        if action == "loop":
            _validate_loop_step(step, section, index, errors)
        elif action == "if":
            _validate_if_step(step, section, index, errors)
        elif action == "expr":
            _validate_expr_step(step, section, index, errors)


def _validate_loop_step(step: dict[str, Any], section: str, index: int, errors: list[dict[str, Any]]) -> None:
    step_id = str(step.get("id") or f"{section}_{index + 1}")
    nested = step.get("steps")
    if not isinstance(nested, list):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: loop.steps must be a list", step_id=step_id))
        return
    args = step.get("args") or {}
    if not isinstance(args, dict):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: loop.args must be an object", step_id=step_id))
        return
    if "over" not in args and "count" not in args:
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: loop requires args.over or args.count", step_id=step_id))
    _validate_steps(nested, section, errors)


def _validate_if_step(step: dict[str, Any], section: str, index: int, errors: list[dict[str, Any]]) -> None:
    step_id = str(step.get("id") or f"{section}_{index + 1}")
    nested = step.get("steps")
    if nested is not None and not isinstance(nested, list):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: if.steps must be a list", step_id=step_id))
        return
    else_steps = step.get("else_steps")
    if else_steps is not None and not isinstance(else_steps, list):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: if.else_steps must be a list", step_id=step_id))
        return
    args = step.get("args") or {}
    if not isinstance(args, dict) or "when" not in args:
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: if requires args.when", step_id=step_id))
    if isinstance(nested, list):
        _validate_steps(nested, section, errors)
    if isinstance(else_steps, list):
        _validate_steps(else_steps, section, errors)


def _validate_expr_step(step: dict[str, Any], section: str, index: int, errors: list[dict[str, Any]]) -> None:
    step_id = str(step.get("id") or f"{section}_{index + 1}")
    args = step.get("args") or {}
    if not isinstance(args, dict):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: expr.args must be an object", step_id=step_id))
        return
    if not args.get("name"):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: expr requires args.name", step_id=step_id))
    if args.get("expr") in (None, ""):
        errors.append(_err(PLAN_SCHEMA_INVALID, f"{step_id}: expr requires args.expr", step_id=step_id))


def _err(code: str, message: str, step_id: str = "") -> dict[str, Any]:
    err = RunError(code, message, step_id=step_id)
    return err.to_dict()
