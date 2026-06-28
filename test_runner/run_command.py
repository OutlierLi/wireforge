from __future__ import annotations

import time
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from test_runner.context import RunContext, create_run_id
from test_runner.error_codes import (
    INTERNAL_ERROR,
    KNOWN_ACTIONS,
    PLAN_SCHEMA_INVALID,
    RUN_TIMEOUT,
    RunError,
    classify_exception,
    classify_step_failure,
    extract_diagnostics,
)
from test_runner.plan_loader import PlanError, load_plan, load_plan_dict
from test_runner.plan_resolver import dry_resolve, resolve_plan_for_report
from test_runner.plan_validator import validate_plan
from test_runner.report_writer import ReportWriter, format_summary
from test_runner.step_executor import StepExecutor

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_ROOT = ROOT / "log" / "run_reports"


@dataclass
class RunOptions:
    dry_run: bool = False
    timeout_ms: int | None = None
    report_root: str | Path | None = None
    stop_on_error: bool = True
    vars: dict[str, Any] = field(default_factory=dict)
    report: str | None = None


class RunCommand:
    @staticmethod
    def schema() -> dict[str, Any]:
        return {
            "version": 1,
            "test_plan_schema": {
                "type": "object",
                "required": ["version", "name", "steps"],
                "properties": {
                    "version": {"type": "integer", "const": 1},
                    "name": {"type": "string", "description": "Test plan name"},
                    "vars": {"type": "object", "description": "Global variables"},
                    "timeout_ms": {"type": "integer", "description": "Overall run timeout in ms"},
                    "setup": {"type": "array", "description": "Pre-test steps"},
                    "steps": {"type": "array", "description": "Main test steps"},
                    "teardown": {"type": "array", "description": "Cleanup steps (always executed)"},
                },
            },
            "step_schema": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string"},
                    "args": {"type": "object"},
                    "save_as": {"type": "string", "description": "Store step result in vars"},
                },
            },
            "supported_actions": sorted(KNOWN_ACTIONS),
            "action_descriptions": {
                "build": "Construct protocol frame via /build",
                "decode": "Decode hex frame via /decode",
                "send": "Send hex frame via serial",
                "wait-frame": "Wait for matching frame on serial",
                "request": "Build + send + wait combination",
                "serial.connect": "Open serial connection",
                "serial.disconnect": "Close serial connection",
                "auto_rule.add": "Add auto-reply rule",
                "auto_rule.remove": "Remove auto-reply rule",
                "assert": "Compare expect values against vars",
                "set_var": "Set a variable in scope",
                "sleep": "Sleep for specified ms",
            },
            "example": "database/runs/all_actions.yaml",
        }

    @staticmethod
    def validate(*, plan: dict[str, Any] | None = None, file: str | None = None) -> dict[str, Any]:
        try:
            loaded = _load_raw(plan=plan, file=file)
        except PlanError as exc:
            return {"ok": False, "errors": [RunError(PLAN_SCHEMA_INVALID, str(exc)).to_dict()]}
        return validate_plan(deepcopy(loaded))

    @staticmethod
    def dry_run(
        *,
        plan: dict[str, Any] | None = None,
        file: str | None = None,
        vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validation = RunCommand.validate(plan=plan, file=file)
        if not validation["ok"]:
            return validation
        loaded = _load_input(plan=plan, file=file)
        return dry_resolve(loaded, vars)

    @staticmethod
    def run(
        *,
        plan: dict[str, Any] | None = None,
        file: str | None = None,
        options: RunOptions | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        opts = _normalize_options(options)
        try:
            loaded = _load_input(plan=plan, file=file)
        except PlanError as exc:
            err = RunError(PLAN_SCHEMA_INVALID, str(exc))
            return _error_response(err)

        validation = validate_plan(deepcopy(loaded))
        if not validation["ok"]:
            err = RunError(
                validation["errors"][0]["code"],
                validation["errors"][0]["message"],
                step_id=validation["errors"][0].get("step_id", ""),
            )
            return _error_response(err)

        plan_name = str(loaded["name"])
        now = datetime.now().astimezone()
        run_id = create_run_id(plan_name, now)
        report_dir = _resolve_report_dir(plan_name, now, opts, run_id)
        plan_path = Path(file) if file else None
        plan_timeout = int(opts.timeout_ms or loaded.get("timeout_ms") or 0)
        deadline = time.monotonic() + plan_timeout / 1000.0 if plan_timeout else None

        ctx = RunContext(
            run_id=run_id,
            plan_name=plan_name,
            plan_path=plan_path,
            report_dir=report_dir,
            start_time=now,
            deadline_monotonic=deadline,
            vars={**(loaded.get("vars") or {}), **opts.vars},
            dry_run=opts.dry_run,
        )
        writer = ReportWriter(ctx, loaded)
        executor = StepExecutor()
        resolved_plan = resolve_plan_for_report(loaded, ctx, executor)
        writer.write_resolved_plan(resolved_plan)

        status = "success"
        error_text = ""
        primary_error: RunError | None = None

        try:
            _execute_section(loaded.get("setup") or [], ctx, writer, executor, section="setup")
            _execute_section(loaded.get("steps") or [], ctx, writer, executor, section="steps", stop_on_error=opts.stop_on_error)
        except RuntimeError as exc:
            status = "fail"
            error_text = str(exc)
            if ctx.primary_error:
                primary_error = ctx.primary_error
            elif "run timeout" in error_text.lower():
                primary_error = RunError(RUN_TIMEOUT, error_text, step_id=ctx.failed_step)
            else:
                primary_error = RunError(INTERNAL_ERROR, error_text, step_id=ctx.failed_step)
        finally:
            _execute_section(loaded.get("teardown") or [], ctx, writer, executor, section="teardown", ignore_error=True)

        total_ms = sum(r.elapsed_ms for r in ctx.records)
        mcp_result = _compact_result(ctx, status, error_text, primary_error, total_ms)
        writer.finish(status, error_text, primary_error=primary_error, mcp_result=mcp_result)

        legacy = {
            "run_id": ctx.run_id,
            "name": plan_name,
            "status": status,
            "error": error_text,
            "report": str(report_dir),
            "summary": format_summary(plan_name, ctx.records, status, error_text, report_dir),
            "steps": [r.__dict__ for r in ctx.records],
        }
        mcp_result["_legacy"] = legacy
        return mcp_result

    @staticmethod
    def read_report(
        report_dir: str,
        *,
        step_id: str | None = None,
        tail_frames: int = 20,
    ) -> dict[str, Any]:
        root = Path(report_dir)
        if not root.is_absolute():
            candidate = ROOT / report_dir
            if candidate.exists():
                root = candidate
            else:
                candidate = DEFAULT_REPORT_ROOT / report_dir
                if candidate.exists():
                    root = candidate

        if not root.exists():
            return _error_response(RunError(INTERNAL_ERROR, f"report not found: {report_dir}"))

        summary_path = root / "summary.json"
        summary: dict[str, Any] = {}
        if summary_path.exists():
            import json
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        result: dict[str, Any] = {"ok": True, "report_dir": str(root), "summary": summary}

        frames_path = root / "frames.log"
        if frames_path.exists():
            lines = frames_path.read_text(encoding="utf-8").splitlines()
            result["recent_frames"] = lines[-tail_frames:]

        if step_id:
            result["step_detail"] = _read_step_detail(root, step_id)

        return result


def run_test_plan(
    file: str,
    *,
    cli_vars: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout_ms: int | None = None,
    report: str | None = None,
) -> dict[str, Any]:
    result = RunCommand.run(
        file=file,
        options=RunOptions(
            dry_run=dry_run,
            timeout_ms=timeout_ms,
            vars=cli_vars or {},
            report=report,
        ),
    )
    legacy = result.pop("_legacy", None)
    if legacy:
        legacy["report_json"] = _load_report_json(legacy.get("report", ""))
        return legacy
    return result


def _load_input(*, plan: dict[str, Any] | None, file: str | None) -> dict[str, Any]:
    if plan is not None:
        return load_plan_dict(plan)
    if file:
        return load_plan(file)
    raise PlanError("plan or file is required")


def _load_raw(*, plan: dict[str, Any] | None, file: str | None) -> dict[str, Any]:
    if plan is not None:
        return deepcopy(plan)
    if file:
        from test_runner.plan_loader import PlanError
        import yaml
        plan_path = Path(file)
        try:
            data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise PlanError(f"plan file not found: {plan_path}") from None
        except Exception as exc:
            raise PlanError(f"failed to load plan: {exc}") from exc
        if not isinstance(data, dict):
            raise PlanError("plan must be a YAML object")
        return data
    raise PlanError("plan or file is required")


def _normalize_options(options: RunOptions | dict[str, Any] | None) -> RunOptions:
    if options is None:
        return RunOptions()
    if isinstance(options, RunOptions):
        return options
    return RunOptions(
        dry_run=bool(options.get("dry_run", False)),
        timeout_ms=options.get("timeout_ms"),
        report_root=options.get("report_root"),
        stop_on_error=bool(options.get("stop_on_error", True)),
        vars=dict(options.get("vars") or {}),
        report=options.get("report"),
    )


def _resolve_report_dir(plan_name: str, now: datetime, opts: RunOptions, run_id: str) -> Path:
    if opts.report:
        return Path(opts.report)
    root = Path(opts.report_root) if opts.report_root else DEFAULT_REPORT_ROOT
    if not root.is_absolute():
        root = ROOT / root
    return root / run_id


def _execute_section(
    steps: list[dict[str, Any]],
    ctx: RunContext,
    writer: ReportWriter,
    executor: StepExecutor,
    *,
    section: str,
    ignore_error: bool = False,
    stop_on_error: bool = True,
) -> None:
    for step in steps:
        if ctx.deadline_monotonic is not None and time.monotonic() > ctx.deadline_monotonic:
            ctx.failed_step = ctx.failed_step or str(step.get("id") or "")
            run_err = RunError(RUN_TIMEOUT, "run timeout", step_id=ctx.failed_step)
            ctx.primary_error = run_err
            writer.record_run_error(run_err)
            raise RuntimeError("run timeout")

        step_id = str(step["id"])
        action = str(step["action"])
        writer.record_step_start(step_id, action)
        record = executor.execute(step, ctx)
        ctx.records.append(record)
        writer.record_step_end(record)

        if record.status != "ok":
            run_err = classify_step_failure(step_id, action, record.result, message=record.error)
            if section == "teardown":
                ctx.teardown_errors.append(run_err.to_dict())
                continue
            ctx.failed_step = step_id
            if ctx.primary_error is None:
                ctx.primary_error = run_err
            if not ignore_error and stop_on_error:
                raise RuntimeError(record.error or f"step failed: {step_id}")


def _compact_result(
    ctx: RunContext,
    status: str,
    error_text: str,
    primary_error: RunError | None,
    total_ms: int,
) -> dict[str, Any]:
    ok = status == "success"
    base: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "run_id": ctx.run_id,
        "report_dir": str(ctx.report_dir),
        "elapsed_ms": total_ms,
    }
    if ok:
        base["summary"] = f"all {len(ctx.records)} steps passed"
        return base

    diag = extract_diagnostics(primary_error)
    if primary_error:
        base["error"] = primary_error.to_dict()
        base["failed_step"] = ctx.failed_step
        base["reason"] = primary_error.message
        base.update(diag)
        base["summary"] = _build_summary_text(ctx, primary_error, diag)
    else:
        base["failed_step"] = ctx.failed_step
        base["reason"] = error_text
        base["summary"] = error_text
    if ctx.teardown_errors:
        base["teardown_errors"] = ctx.teardown_errors
    return base


def _build_summary_text(ctx: RunContext, error: RunError, diag: dict[str, Any]) -> str:
    parts = [f"{ctx.failed_step} {error.message}"]
    if diag.get("received_frames") is not None:
        parts.append(f"received {diag['received_frames']} frames")
    if diag.get("mismatch_summary"):
        parts.append("; ".join(str(x) for x in diag["mismatch_summary"][:3]))
    return ", ".join(parts)


def _error_response(error: RunError, report_dir: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error.to_dict()}
    if report_dir:
        out["report_dir"] = report_dir
    return out


def _load_report_json(report_dir: str) -> dict[str, Any]:
    import json
    path = Path(report_dir) / "report.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _read_step_detail(root: Path, step_id: str) -> dict[str, Any]:
    import json

    detail: dict[str, Any] = {"step_id": step_id}
    timeline = root / "timeline.log"
    if timeline.exists():
        detail["timeline"] = [line for line in timeline.read_text(encoding="utf-8").splitlines() if step_id in line]

    errors = root / "errors.log"
    if errors.exists():
        detail["errors"] = [
            json.loads(line)
            for line in errors.read_text(encoding="utf-8").splitlines()
            if line.strip() and step_id in line
        ]

    report_path = root / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for step in report.get("steps") or []:
            if step.get("id") == step_id:
                detail["result"] = step.get("result")
                detail["status"] = step.get("status")
                detail["elapsed_ms"] = step.get("elapsed_ms")
                break

    return detail
