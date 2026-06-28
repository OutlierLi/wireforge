from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
import time

from console.runner.context import RunContext, create_run_id
from console.runner.executor import StepExecutor
from console.runner.plan import load_plan
from console.runner.report_writer import ReportWriter, format_summary
from console.runner.variables import resolve_value

ROOT = Path(__file__).resolve().parent.parent.parent


def run_test_plan(
    file: str,
    *,
    cli_vars: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout_ms: int | None = None,
    report: str | None = None,
) -> dict[str, Any]:
    plan_path = Path(file)
    plan = load_plan(plan_path)
    plan_name = str(plan["name"])
    now = datetime.now().astimezone()
    report_dir = Path(report) if report else ROOT / "log" / "run_reports" / f"{plan_name}_{now.strftime('%Y%m%d_%H%M%S')}"
    plan_timeout = int(timeout_ms or plan.get("timeout_ms") or 0)
    deadline = time.monotonic() + plan_timeout / 1000.0 if plan_timeout else None
    ctx = RunContext(
        run_id=create_run_id(),
        plan_name=plan_name,
        plan_path=plan_path,
        report_dir=report_dir,
        start_time=now,
        deadline_monotonic=deadline,
        vars={**(plan.get("vars") or {}), **(cli_vars or {})},
        dry_run=dry_run,
    )
    writer = ReportWriter(ctx, plan)
    executor = StepExecutor()
    resolved_plan = _resolve_plan_for_report(plan, ctx, executor)
    writer.write_resolved_plan(resolved_plan)

    status = "success"
    error = ""
    try:
        _execute_section(plan.get("setup") or [], ctx, writer, executor, ignore_error=False)
        _execute_section(plan.get("steps") or [], ctx, writer, executor, ignore_error=False)
    except RuntimeError as exc:
        status = "fail"
        error = str(exc)
    finally:
        _execute_section(plan.get("teardown") or [], ctx, writer, executor, ignore_error=True)

    report_data = writer.finish(status, error)
    return {
        "run_id": ctx.run_id,
        "name": plan_name,
        "status": status,
        "error": error,
        "report": str(report_dir),
        "summary": format_summary(plan_name, ctx.records, status, error, report_dir),
        "steps": [r.__dict__ for r in ctx.records],
        "report_json": report_data,
    }


def _execute_section(
    steps: list[dict[str, Any]],
    ctx: RunContext,
    writer: ReportWriter,
    executor: StepExecutor,
    *,
    ignore_error: bool,
) -> None:
    for step in steps:
        if ctx.deadline_monotonic is not None and time.monotonic() > ctx.deadline_monotonic:
            raise RuntimeError("run timeout")
        writer.record_step_start(str(step["id"]), str(step["action"]))
        record = executor.execute(step, ctx)
        ctx.records.append(record)
        writer.record_step_end(record)
        if record.status != "ok" and not ignore_error:
            raise RuntimeError(record.error or f"step failed: {record.id}")


def _resolve_plan_for_report(plan: dict[str, Any], ctx: RunContext, executor: StepExecutor) -> dict[str, Any]:
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

