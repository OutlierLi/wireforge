from __future__ import annotations

import time
from typing import Any

from test_runner.conditions import evaluate_when
from test_runner.context import RunContext
from test_runner.error_codes import RUN_TIMEOUT, RunError, classify_step_failure
from test_runner.loop_helpers import loop_index_bindings, loop_temp_index_keys
from test_runner.step_executor import StepExecutor, StepRecord
from test_runner.variables import VariableError, resolve_value


def execute_steps(
    steps: list[dict[str, Any]],
    ctx: RunContext,
    executor: StepExecutor,
    writer: Any,
    *,
    section: str,
    ignore_error: bool = False,
    stop_on_error: bool = True,
    id_prefix: str = "",
) -> None:
    for index, step in enumerate(steps):
        if ctx.deadline_monotonic is not None and time.monotonic() > ctx.deadline_monotonic:
            ctx.failed_step = ctx.failed_step or _step_id(step, id_prefix, index)
            run_err = RunError(RUN_TIMEOUT, "run timeout", step_id=ctx.failed_step)
            ctx.primary_error = run_err
            writer.record_run_error(run_err)
            raise RuntimeError("run timeout")

        step_id = _step_id(step, id_prefix, index)
        action = str(step["action"])

        if action == "loop":
            _execute_loop_step(
                step, step_id, ctx, executor, writer,
                section=section,
                ignore_error=ignore_error,
                stop_on_error=stop_on_error,
                id_prefix=step_id,
            )
            continue

        if action == "if":
            _execute_if_step(
                step, step_id, ctx, executor, writer,
                section=section,
                ignore_error=ignore_error,
                stop_on_error=stop_on_error,
                id_prefix=step_id,
            )
            continue

        writer.record_step_start(step_id, action)
        record = executor.execute(_with_runtime_id(step, step_id), ctx)
        ctx.records.append(record)
        writer.record_step_end(record)

        if record.status != "ok":
            _handle_step_failure(
                step_id, action, record, ctx, writer,
                section=section,
                ignore_error=ignore_error,
                stop_on_error=stop_on_error,
            )


def _execute_loop_step(
    step: dict[str, Any],
    step_id: str,
    ctx: RunContext,
    executor: StepExecutor,
    writer: Any,
    *,
    section: str,
    ignore_error: bool,
    stop_on_error: bool,
    id_prefix: str,
) -> None:
    args = dict(step.get("args") or {})
    nested = step.get("steps") or []
    if not isinstance(nested, list):
        raise RuntimeError(f"{step_id}: loop.steps must be a list")

    scope = executor._scope(ctx)
    item_var = str(args.get("as") or args.get("item_as") or "item")
    index_var = args.get("index_as")
    count_mode = "count" in args

    iterations: list[tuple[int, Any | None]] = []
    if "over" in args:
        over = resolve_value(args["over"], scope)
        if isinstance(over, str):
            over = resolve_value("${" + over + "}", scope)
        if not isinstance(over, list):
            raise RuntimeError(f"{step_id}: loop.over must resolve to a list")
        iterations = [(i, item) for i, item in enumerate(over)]
    elif "count" in args:
        count = int(resolve_value(args["count"], scope))
        start = int(resolve_value(args.get("start", 0), scope))
        iterations = [(start + i, None) for i in range(count)]
    else:
        raise RuntimeError(f"{step_id}: loop requires args.over or args.count")

    writer.record_step_start(step_id, "loop")
    loop_start = time.monotonic()
    loop_status = "ok"
    loop_error = ""
    loop_result: dict[str, Any] = {"iterations": len(iterations)}

    outer = dict(ctx.vars)
    loop_temp_keys = {item_var, *loop_temp_index_keys(index_var, count_mode=count_mode)}
    last_body_vars: dict[str, Any] = {}

    for iter_index, (i, item) in enumerate(iterations):
        loop_scope = {item_var: item, **loop_index_bindings(i, index_var, count_mode=count_mode)}

        ctx.vars.clear()
        ctx.vars.update(outer)
        ctx.vars.update(loop_scope)
        try:
            execute_steps(
                nested,
                ctx,
                executor,
                writer,
                section=section,
                ignore_error=ignore_error,
                stop_on_error=stop_on_error,
                id_prefix=f"{id_prefix}[{iter_index}]",
            )
            last_body_vars = {
                k: v for k, v in ctx.vars.items()
                if k not in loop_temp_keys
            }
        except RuntimeError as exc:
            loop_status = "fail"
            loop_error = str(exc)
            break

    ctx.vars.clear()
    ctx.vars.update(outer)
    ctx.vars.update(last_body_vars)

    elapsed = int((time.monotonic() - loop_start) * 1000)
    record = StepRecord(step_id, "loop", loop_status, elapsed, loop_error, result=loop_result)
    ctx.records.append(record)
    writer.record_step_end(record)
    ctx.step_results[step_id] = loop_result
    ctx.vars[step_id] = loop_result

    if loop_status != "ok":
        if not (section == "teardown" and ignore_error):
            if stop_on_error:
                raise RuntimeError(loop_error or f"step failed: {step_id}")


def _execute_if_step(
    step: dict[str, Any],
    step_id: str,
    ctx: RunContext,
    executor: StepExecutor,
    writer: Any,
    *,
    section: str,
    ignore_error: bool,
    stop_on_error: bool,
    id_prefix: str,
) -> None:
    args = dict(step.get("args") or {})
    when = args.get("when")
    if when is None:
        raise RuntimeError(f"{step_id}: if requires args.when")

    scope = executor._scope(ctx)
    branch = evaluate_when(when, scope)
    nested = step.get("steps") if branch else step.get("else_steps")
    if nested is None:
        nested = []
    if not isinstance(nested, list):
        raise RuntimeError(f"{step_id}: if branch steps must be a list")

    writer.record_step_start(step_id, "if")
    if_start = time.monotonic()
    if_status = "ok"
    if_error = ""
    if_result = {"branch": "then" if branch else "else", "matched": branch}

    if nested:
        try:
            execute_steps(
                nested,
                ctx,
                executor,
                writer,
                section=section,
                ignore_error=ignore_error,
                stop_on_error=stop_on_error,
                id_prefix=f"{id_prefix}.{'then' if branch else 'else'}",
            )
        except RuntimeError as exc:
            if_status = "fail"
            if_error = str(exc)

    elapsed = int((time.monotonic() - if_start) * 1000)
    record = StepRecord(step_id, "if", if_status, elapsed, if_error, result=if_result)
    ctx.records.append(record)
    writer.record_step_end(record)
    ctx.step_results[step_id] = if_result
    ctx.vars[step_id] = if_result

    if if_status != "ok":
        if not (section == "teardown" and ignore_error):
            if stop_on_error:
                raise RuntimeError(if_error or f"step failed: {step_id}")


def _handle_step_failure(
    step_id: str,
    action: str,
    record: StepRecord,
    ctx: RunContext,
    writer: Any,
    *,
    section: str,
    ignore_error: bool,
    stop_on_error: bool,
) -> None:
    run_err = classify_step_failure(step_id, action, record.result, message=record.error)
    if section == "teardown":
        ctx.teardown_errors.append(run_err.to_dict())
        return
    ctx.failed_step = step_id
    if ctx.primary_error is None:
        ctx.primary_error = run_err
    if not ignore_error and stop_on_error:
        raise RuntimeError(record.error or f"step failed: {step_id}")


def _step_id(step: dict[str, Any], prefix: str, index: int) -> str:
    raw = str(step.get("id") or f"step_{index + 1}")
    return f"{prefix}.{raw}" if prefix else raw


def _with_runtime_id(step: dict[str, Any], step_id: str) -> dict[str, Any]:
    patched = dict(step)
    patched["id"] = step_id
    return patched
