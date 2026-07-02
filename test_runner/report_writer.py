from __future__ import annotations

import json
import shutil
import traceback
from pathlib import Path
from typing import Any

import yaml

from test_runner.context import RunContext, StepRecord, now_iso
from test_runner.error_codes import RunError


class ReportWriter:
    def __init__(self, ctx: RunContext, original_plan: dict[str, Any]):
        self.ctx = ctx
        self.original_plan = original_plan
        self.ctx.report_dir.mkdir(parents=True, exist_ok=True)
        if ctx.plan_path and ctx.plan_path.exists():
            shutil.copyfile(ctx.plan_path, self.ctx.report_dir / "plan.yaml")
        else:
            (self.ctx.report_dir / "plan.yaml").write_text(
                yaml.safe_dump(original_plan, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        self._timeline = self.ctx.report_dir / "timeline.log"
        self._frames = self.ctx.report_dir / "frames.log"
        self._errors = self.ctx.report_dir / "errors.log"
        self._data_frames = self.ctx.report_dir / "data_frames.log"
        self._debug_log = self.ctx.report_dir / "debug.log"
        for path in (self._timeline, self._frames, self._errors, self._data_frames, self._debug_log):
            path.touch(exist_ok=True)

    def write_resolved_plan(self, plan: dict[str, Any]) -> None:
        (self.ctx.report_dir / "resolved_plan.yaml").write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def record_step_start(self, step_id: str, action: str) -> None:
        self._append(self._timeline, f"[{now_iso()}] START {step_id} action={action}\n")

    def record_step_end(self, record: StepRecord) -> None:
        line = f"[{now_iso()}] {record.status.upper()} {record.id} action={record.action} elapsed_ms={record.elapsed_ms}"
        if record.error:
            line += f" error={record.error}"
        self._append(self._timeline, line + "\n")
        self._record_frames(record)
        if record.status != "ok":
            self._record_error(record)

    def record_run_error(self, error: RunError, *, tb: str = "") -> None:
        payload = error.to_dict()
        if tb:
            payload["traceback"] = tb
        self._append(self._errors, json.dumps(payload, ensure_ascii=False) + "\n")

    def finish(
        self,
        status: str,
        error: str = "",
        *,
        primary_error: RunError | None = None,
        mcp_result: dict[str, Any] | None = None,
        execution_report: bool = False,
        original_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        total_ms = sum(r.elapsed_ms for r in self.ctx.records)
        report = {
            "run_id": self.ctx.run_id,
            "name": self.ctx.plan_name,
            "status": status,
            "error": error,
            "started_at": self.ctx.start_time.isoformat(timespec="seconds"),
            "total_ms": total_ms,
            "steps": [r.__dict__ for r in self.ctx.records],
            "vars": self.ctx.vars,
            "failed_step": self.ctx.failed_step,
            "teardown_errors": self.ctx.teardown_errors,
        }
        if self.ctx.lab is not None:
            report["lab"] = self.ctx.lab.to_dict()
        if primary_error:
            report["structured_error"] = primary_error.to_dict()

        (self.ctx.report_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary_json = {
            "run_id": self.ctx.run_id,
            "name": self.ctx.plan_name,
            "status": status,
            "failed_step": self.ctx.failed_step,
            "error": primary_error.to_dict() if primary_error else None,
            "elapsed_ms": total_ms,
            "teardown_errors": self.ctx.teardown_errors,
            "steps_summary": [
                {"id": r.id, "action": r.action, "status": r.status, "elapsed_ms": r.elapsed_ms}
                for r in self.ctx.records
            ],
        }
        if self.ctx.lab is not None:
            summary_json["lab"] = self.ctx.lab.to_dict()
        (self.ctx.report_dir / "summary.json").write_text(
            json.dumps(summary_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        (self.ctx.report_dir / "summary.txt").write_text(
            format_summary(self.ctx.plan_name, self.ctx.records, status, error, self.ctx.report_dir),
            encoding="utf-8",
        )

        if mcp_result is not None:
            (self.ctx.report_dir / "mcp_result.json").write_text(
                json.dumps(mcp_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if execution_report:
            from test_runner.execution_report import write_execution_report_files

            write_execution_report_files(
                self.ctx,
                original_plan or self.original_plan,
                status=status,
                error_text=error,
                primary_error=primary_error,
                total_ms=total_ms,
            )

        return report

    def _record_frames(self, record: StepRecord) -> None:
        data = record.result.get("data") if isinstance(record.result, dict) else None
        if not isinstance(data, dict):
            return
        lab_meta = data.get("_lab") if isinstance(data.get("_lab"), dict) else {}
        for key in ("frame", "frame_hex"):
            if data.get(key):
                self._append_frame_line(record, lab_meta, f"{key}={data[key]}")
        if data.get("debug_line"):
            self._append_debug_line(record, lab_meta, str(data["debug_line"]))
        decoded = data.get("decoded") or data.get("values")
        if decoded:
            self._append_frame_line(record, lab_meta, f"decoded={json.dumps(decoded, ensure_ascii=False)}")
        request = data.get("request")
        response = data.get("response")
        if isinstance(request, dict) and request.get("frame_hex"):
            self._append_frame_line(record, lab_meta, f"tx={request['frame_hex']}")
            if request.get("decoded"):
                self._append_frame_line(record, lab_meta, f"tx_decoded={json.dumps(request['decoded'], ensure_ascii=False)}")
        if isinstance(response, dict) and response.get("frame_hex"):
            self._append_frame_line(record, lab_meta, f"rx={response['frame_hex']}")
            if response.get("decoded"):
                self._append_frame_line(record, lab_meta, f"rx_decoded={json.dumps(response['decoded'], ensure_ascii=False)}")
        detail = record.result.get("detail") if isinstance(record.result, dict) else None
        if isinstance(detail, dict) and detail.get("last_decoded"):
            self._append_frame_line(record, lab_meta, f"last_decoded={json.dumps(detail['last_decoded'], ensure_ascii=False)}")

    def _append_frame_line(self, record: StepRecord, lab_meta: dict[str, Any], text: str) -> None:
        prefix = _lab_prefix(record, lab_meta)
        line = f"[{now_iso()}] {prefix}{text}\n"
        self._append(self._frames, line)
        role = str(lab_meta.get("role") or "")
        channel = str(lab_meta.get("channel") or "")
        if role != "debug_uart" and channel != "debug":
            self._append(self._data_frames, line)

    def _append_debug_line(self, record: StepRecord, lab_meta: dict[str, Any], text: str) -> None:
        prefix = _lab_prefix(record, lab_meta)
        self._append(self._debug_log, f"[{now_iso()}] {prefix}{text}\n")

    def _record_error(self, record: StepRecord) -> None:
        payload: dict[str, Any] = {
            "step_id": record.id,
            "action": record.action,
            "error": record.error,
            "result": record.result,
        }
        self._append(self._errors, json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _append(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text)


def format_summary(plan_name: str, records: list[StepRecord], status: str, error: str, report_dir: Path) -> str:
    lines = [f"RUN {plan_name}"]
    for record in records:
        label = "OK" if record.status == "ok" else "FAIL"
        lines.append(f"[{label}] {record.id:<24} {record.elapsed_ms}ms")
    lines.append("")
    if status == "success":
        lines.append(f"SUCCESS total={sum(r.elapsed_ms for r in records)}ms")
    else:
        lines.append(f"reason: {error}")
        lines.append("FAIL")
    lines.append(f"report: {report_dir}")
    return "\n".join(lines) + "\n"


def _lab_prefix(record: StepRecord, lab_meta: dict[str, Any]) -> str:
    target = str(lab_meta.get("target") or "")
    channel = str(lab_meta.get("channel") or "")
    conn = str(lab_meta.get("conn") or "")
    if target or channel:
        scope = ".".join(part for part in (target, channel) if part)
        if conn:
            return f"{record.id} [{scope} {conn}] "
        return f"{record.id} [{scope}] "
    return f"{record.id} "
