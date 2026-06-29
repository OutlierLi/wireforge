"""Execution test command — real serial runs with enriched reports."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from test_runner.execution_report import EXECUTION_REPORT_VERSION
from test_runner.plan_validator import validate_plan
from test_runner.run_command import (
    DEFAULT_REPORT_ROOT,
    RunCommand,
    RunOptions,
    _error_response,
    _load_input,
    _load_raw,
)
from test_runner.error_codes import PLAN_SCHEMA_INVALID, RunError
from test_runner.plan_loader import PlanError

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXEC_REPORT_ROOT = ROOT / "log" / "exec_reports"


@dataclass
class ExecOptions:
    timeout_ms: int | None = None
    report_root: str | Path | None = None
    stop_on_error: bool = True
    vars: dict[str, Any] = field(default_factory=dict)
    report: str | None = None
    skip_build_check: bool = False


class ExecCommand:
    """Real-device / real-serial TestPlan execution (distinct from test MCP validate/dry_run)."""

    @staticmethod
    def schema() -> dict[str, Any]:
        base = RunCommand.schema()
        return {
            "version": EXECUTION_REPORT_VERSION,
            "role": "execution_test",
            "description": (
                "真实串口执行 TestPlan，生成 execution_report.json / execution_report.md。"
                "编排校验请用 wireforge-test MCP (test.validate / test.dry_run)。"
            ),
            "test_plan_schema": {
                **base.get("test_plan_schema", {}),
                "optional_execution_fields": {
                    "purpose": "测试目的（写入报告）",
                    "description": "测试描述",
                    "expected_results": [
                        {
                            "step_id": "wait_init_ack",
                            "description": "收到 AFN00 确认帧",
                            "expect": {"afn": "00", "di": "E8010001"},
                        }
                    ],
                    "test_flow": [
                        "serial.connect",
                        "build + send 初始化",
                        "wait-frame 确认",
                    ],
                    "doc": "database/examples/mock_auto_ack.md",
                },
            },
            "execution_template": "database/templates/execution_test_plan.yaml",
            "example_plan": "database/runs/mock_auto_ack.yaml",
            "report_files": {
                "execution_report_json": "execution_report.json",
                "execution_report_md": "execution_report.md",
                "serial_trace": "execution_report.json → serial_trace[]",
                "legacy": ["report.json", "summary.json", "frames.log", "timeline.log"],
            },
            "default_report_root": str(DEFAULT_EXEC_REPORT_ROOT),
            "workflow": [
                "Phase 0: protocol MCP + test MCP validate/dry_run",
                "编写 YAML（含 purpose / expected_results / test_flow）",
                "exec_test.run(file, options.vars) — 真实串口执行",
                "exec_test.read_report(report_dir) — 读结构化报告",
            ],
            "supported_actions": base.get("supported_actions"),
        }

    @staticmethod
    def run(
        *,
        plan: dict[str, Any] | None = None,
        file: str | None = None,
        options: ExecOptions | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        opts = _normalize_exec_options(options)

        try:
            loaded = _load_input(plan=plan, file=file)
        except PlanError as exc:
            return _error_response(RunError(PLAN_SCHEMA_INVALID, str(exc)))

        validation = validate_plan(deepcopy(loaded))
        if not validation["ok"]:
            err = RunError(
                validation["errors"][0]["code"],
                validation["errors"][0]["message"],
                step_id=validation["errors"][0].get("step_id", ""),
            )
            return _error_response(err)

        run_opts = RunOptions(
            dry_run=False,
            timeout_ms=opts.timeout_ms,
            report_root=opts.report_root or DEFAULT_EXEC_REPORT_ROOT,
            stop_on_error=opts.stop_on_error,
            vars=opts.vars,
            report=opts.report,
            skip_build_check=opts.skip_build_check,
            execution_report=True,
        )

        result = RunCommand.run(plan=plan, file=file, options=run_opts)
        if isinstance(result, dict) and result.get("report_dir"):
            report_path = Path(str(result["report_dir"])) / "execution_report.json"
            if report_path.exists():
                import json
                result["execution_report"] = json.loads(
                    report_path.read_text(encoding="utf-8")
                )
        return result

    @staticmethod
    def read_report(
        report_dir: str,
        *,
        step_id: str | None = None,
        format: str = "full",
    ) -> dict[str, Any]:
        root = Path(report_dir)
        if not root.is_absolute():
            for candidate in (ROOT / report_dir, DEFAULT_EXEC_REPORT_ROOT / report_dir, DEFAULT_REPORT_ROOT / report_dir):
                if candidate.exists():
                    root = candidate
                    break

        if not root.exists():
            return {"ok": False, "error": {"code": "REPORT_NOT_FOUND", "message": f"report not found: {report_dir}"}}

        import json

        exec_path = root / "execution_report.json"
        if not exec_path.exists():
            legacy = RunCommand.read_report(str(root), step_id=step_id)
            legacy["ok"] = bool(legacy.get("ok", True))
            legacy["note"] = "execution_report.json missing; returning legacy summary"
            return legacy

        report = json.loads(exec_path.read_text(encoding="utf-8"))
        out: dict[str, Any] = {
            "ok": True,
            "report_dir": str(root),
            "execution_report": report,
        }
        md_path = root / "execution_report.md"
        if md_path.exists():
            out["execution_report_md"] = md_path.read_text(encoding="utf-8")

        if format == "compact":
            out["compact"] = {
                "run_id": report.get("run_id"),
                "name": report.get("name"),
                "status": report.get("status"),
                "elapsed_ms": report.get("elapsed_ms"),
                "purpose": (report.get("test_metadata") or {}).get("purpose"),
                "error_analysis": report.get("error_analysis"),
                "serial_trace_count": len(report.get("serial_trace") or []),
            }

        if step_id:
            out["step_detail"] = RunCommand.read_report(str(root), step_id=step_id).get("step_detail")

        return out


def _normalize_exec_options(options: ExecOptions | dict[str, Any] | None) -> ExecOptions:
    if options is None:
        return ExecOptions()
    if isinstance(options, ExecOptions):
        return options
    return ExecOptions(
        timeout_ms=options.get("timeout_ms"),
        report_root=options.get("report_root"),
        stop_on_error=bool(options.get("stop_on_error", True)),
        vars=dict(options.get("vars") or {}),
        report=options.get("report"),
        skip_build_check=bool(options.get("skip_build_check", False)),
    )
