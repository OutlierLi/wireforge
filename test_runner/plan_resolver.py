from __future__ import annotations

from copy import deepcopy
from typing import Any

from test_runner.error_codes import PLAN_VAR_UNRESOLVED, RunError
from test_runner.loop_helpers import loop_index_bindings
from test_runner.step_executor import StepExecutor
from test_runner.variables import VariableError, resolve_value

MAX_DRY_RUN_LOOP_EXPAND = 32


def dry_resolve(plan: dict[str, Any], vars: dict[str, Any] | None = None) -> dict[str, Any]:
    scope = {**(plan.get("vars") or {}), **(vars or {})}
    executor = StepExecutor()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
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
            resolved_step = _resolve_step_tree_dry(step, executor, ctx)
            if str(step.get("action")) == "loop":
                preview = _build_loop_preview(step, ctx_vars, executor)
                if preview:
                    resolved_step["loop_preview"] = preview
            resolved_items.append(resolved_step)
            _collect_unresolved_refs(resolved_step, str(step.get("id") or ""), warnings)
            if isinstance(resolved_step.get("loop_preview"), dict):
                for preview_step in resolved_step["loop_preview"].get("steps") or []:
                    _collect_unresolved_refs(
                        preview_step,
                        str(preview_step.get("id") or step.get("id") or ""),
                        warnings,
                    )
        resolved[section] = resolved_items

    return {
        "ok": not errors,
        "resolved_plan": resolved,
        "errors": errors,
        "warnings": warnings or None,
    }


def _resolve_loop_iterations(args: dict[str, Any], scope: dict[str, Any]) -> list[tuple[int, Any | None]] | None:
    try:
        if "over" in args:
            over = resolve_value(args["over"], scope)
            if isinstance(over, str):
                over = resolve_value("${" + over + "}", scope)
            if not isinstance(over, list):
                return None
            return [(i, item) for i, item in enumerate(over)]
        if "count" in args:
            count = int(resolve_value(args["count"], scope))
            start = int(resolve_value(args.get("start", 0), scope))
            return [(start + i, None) for i in range(count)]
    except (VariableError, TypeError, ValueError):
        return None
    return None


def _build_loop_preview(
    step: dict[str, Any],
    scope: dict[str, Any],
    executor: StepExecutor,
    *,
    max_expand: int = MAX_DRY_RUN_LOOP_EXPAND,
) -> dict[str, Any] | None:
    args = step.get("args") or {}
    nested = step.get("steps") or []
    if not isinstance(args, dict) or not isinstance(nested, list):
        return None

    iterations = _resolve_loop_iterations(args, scope)
    if not iterations:
        return None

    item_var = str(args.get("as") or args.get("item_as") or "item")
    index_var = args.get("index_as")
    count_mode = "count" in args
    total = len(iterations)
    preview_iterations = iterations[:max_expand]
    preview_steps: list[dict[str, Any]] = []

    for iter_index, (i, item) in enumerate(preview_iterations):
        iter_scope = dict(scope)
        iter_scope[item_var] = item
        iter_scope.update(loop_index_bindings(i, index_var, count_mode=count_mode))

        class _IterCtx:
            vars = iter_scope
            step_results: dict[str, Any] = {}

        for child in nested:
            resolved_child = executor.resolve_step(child, _IterCtx(), soft=True)
            preview_steps.append({
                **resolved_child,
                "_loop_preview": {
                    "parent_id": step.get("id"),
                    "iteration": iter_index,
                    "index": i,
                },
            })

    return {
        "iterations": total,
        "expanded": len(preview_iterations),
        "truncated": total > max_expand,
        "steps": preview_steps,
    }


def _collect_unresolved_refs(value: Any, step_id: str, warnings: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if "_loop_preview" in value and len(value) == 1:
            return
        for key, child in value.items():
            if key == "loop_preview":
                continue
            _collect_unresolved_refs(child, step_id, warnings)
        return
    if isinstance(value, list):
        for child in value:
            _collect_unresolved_refs(child, step_id, warnings)
        return
    if isinstance(value, str) and "${" in value:
        warnings.append(RunError(
            PLAN_VAR_UNRESOLVED,
            f"runtime variable: {value}",
            step_id=step_id,
        ).to_dict())


def _resolve_step_tree_dry(step: dict[str, Any], executor: StepExecutor, ctx: Any) -> dict[str, Any]:
    return executor.resolve_step(step, ctx, soft=True)


def resolve_plan_for_report(plan: dict[str, Any], ctx: Any, executor: StepExecutor) -> dict[str, Any]:
    resolved = deepcopy(plan)
    for section in ("setup", "steps", "teardown"):
        items = resolved.get(section)
        if not isinstance(items, list):
            continue
        resolved_items = []
        for step in items:
            try:
                resolved_items.append(_resolve_step_tree(step, executor, ctx))
            except Exception:
                resolved_items.append(step)
        resolved[section] = resolved_items
    resolved["vars"] = resolve_value(resolved.get("vars") or {}, ctx.vars)
    return resolved


def _resolve_step_tree(step: dict[str, Any], executor: StepExecutor, ctx: Any) -> dict[str, Any]:
    return executor.resolve_step(step, ctx)
