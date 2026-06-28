from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class StepRecord:
    id: str
    action: str
    status: str
    elapsed_ms: int
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    run_id: str
    plan_name: str
    plan_path: Path | None
    report_dir: Path
    start_time: datetime
    deadline_monotonic: float | None
    vars: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    records: list[StepRecord] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    failed_step: str = ""
    teardown_errors: list[dict[str, Any]] = field(default_factory=list)
    primary_error: dict[str, Any] | None = None


def create_run_id(plan_name: str, when: datetime | None = None) -> str:
    ts = (when or datetime.now().astimezone()).strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in plan_name)
    return f"{safe_name}_{ts}"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
