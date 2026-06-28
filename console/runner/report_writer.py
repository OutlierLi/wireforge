from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from console.runner.context import RunContext, StepRecord, now_iso


class ReportWriter:
    def __init__(self, ctx: RunContext, original_plan: dict[str, Any]):
        self.ctx = ctx
        self.original_plan = original_plan
        self.ctx.report_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ctx.plan_path, self.ctx.report_dir / "plan.yaml")
        self._timeline = self.ctx.report_dir / "timeline.log"
        self._frames = self.ctx.report_dir / "frames.log"

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

    def finish(self, status: str, error: str = "") -> dict[str, Any]:
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
        }
        (self.ctx.report_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.ctx.report_dir / "summary.txt").write_text(
            format_summary(self.ctx.plan_name, self.ctx.records, status, error, self.ctx.report_dir),
            encoding="utf-8",
        )
        return report

    def _record_frames(self, record: StepRecord) -> None:
        data = record.result.get("data") if isinstance(record.result, dict) else None
        if not isinstance(data, dict):
            return
        for key in ("frame", "frame_hex"):
            if data.get(key):
                self._append(self._frames, f"[{now_iso()}] {record.id} {key}={data[key]}\n")
        request = data.get("request")
        response = data.get("response")
        if isinstance(request, dict) and request.get("frame_hex"):
            self._append(self._frames, f"[{now_iso()}] {record.id} tx={request['frame_hex']}\n")
        if isinstance(response, dict) and response.get("frame_hex"):
            self._append(self._frames, f"[{now_iso()}] {record.id} rx={response['frame_hex']}\n")

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

