from __future__ import annotations

from copy import deepcopy
from typing import Any

from test_runner.error_codes import PLAN_VAR_UNRESOLVED, RunError
from test_runner.step_executor import StepExecutor
from test_runner.variables import VariableError, resolve_value


def dry_resolve(plan: dict[str, Any], vars: dict[str, Any] | None = None) -> dict[str, Any]:
    scope = {**(plan.get("vars") or {}), **(vars or {})}
    executor = StepExecutor()
    errors: list[dict[str, Any]] = []
    resolved = deepcopy(plan)

    try:
        resolved["vars"] = resolve_value({**(plan.get("vars") or {}), **(vars or {})}, scope)
    except VariableError as exc:
        errors.append(RunError(PLAN_VAR_UNRESOLVED, str(exc)).to_dict())

    ctx_vars = dict(resolved.get("vars") or scope)

    class _Ctx:
        vars = ctx_vars
        step_results: dict[str, Any] = {}

    ctx = _Ctx()

    for section in ("setup", "steps", "teardown"):
        items = resolved.get(section)
        if not isinstance(items, list):
            continue
        resolved_items = []
        for step in items:
            try:
                resolved_items.append(executor.resolve_step(step, ctx))  # type: ignore[arg-type]
            except VariableError as exc:
                errors.append(RunError(
                    PLAN_VAR_UNRESOLVED,
                    str(exc),
                    step_id=str(step.get("id") or ""),
                ).to_dict())
                resolved_items.append(step)
            except Exception as exc:
                errors.append(RunError(
                    PLAN_VAR_UNRESOLVED,
                    str(exc),
                    step_id=str(step.get("id") or ""),
                ).to_dict())
                resolved_items.append(step)
        resolved[section] = resolved_items

    return {"ok": not errors, "resolved_plan": resolved, "errors": errors}


def resolve_plan_for_report(plan: dict[str, Any], ctx: Any, executor: StepExecutor) -> dict[str, Any]:
    resolved = deepcopy(plan)
    for section in ("setup", "steps", "teardown"):
        items = resolved.get(section)
        if not isinstance(items, list):
            continue
        resolved_items = []
        for step in items:
            try:
                resolved_items.append(executor.resolve_step(step, ctx))
            except Exception:
                resolved_items.append(step)
        resolved[section] = resolved_items
    resolved["vars"] = resolve_value(resolved.get("vars") or {}, ctx.vars)
    return resolved
