from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid


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
    plan_path: Path
    report_dir: Path
    start_time: datetime
    deadline_monotonic: float | None
    vars: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    records: list[StepRecord] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False


def create_run_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

