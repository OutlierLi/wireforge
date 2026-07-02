from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PLAN_BUILD_SCHEMA_MISMATCH = "PLAN_BUILD_SCHEMA_MISMATCH"
PLAN_SCHEMA_INVALID = "PLAN_SCHEMA_INVALID"
PLAN_VAR_UNRESOLVED = "PLAN_VAR_UNRESOLVED"
PLAN_ACTION_UNKNOWN = "PLAN_ACTION_UNKNOWN"
STEP_TIMEOUT = "STEP_TIMEOUT"
STEP_FAILED = "STEP_FAILED"
SERIAL_NOT_CONNECTED = "SERIAL_NOT_CONNECTED"
SERIAL_WRITE_FAILED = "SERIAL_WRITE_FAILED"
WAIT_FRAME_TIMEOUT = "WAIT_FRAME_TIMEOUT"
MATCH_FAILED = "MATCH_FAILED"
BUILD_FAILED = "BUILD_FAILED"
DECODE_FAILED = "DECODE_FAILED"
AUTO_RULE_FAILED = "AUTO_RULE_FAILED"
RUN_TIMEOUT = "RUN_TIMEOUT"
INTERNAL_ERROR = "INTERNAL_ERROR"

ALL_ERROR_CODES = {
    PLAN_SCHEMA_INVALID,
    PLAN_VAR_UNRESOLVED,
    PLAN_ACTION_UNKNOWN,
    PLAN_BUILD_SCHEMA_MISMATCH,
    STEP_TIMEOUT,
    STEP_FAILED,
    SERIAL_NOT_CONNECTED,
    SERIAL_WRITE_FAILED,
    WAIT_FRAME_TIMEOUT,
    MATCH_FAILED,
    BUILD_FAILED,
    DECODE_FAILED,
    AUTO_RULE_FAILED,
    RUN_TIMEOUT,
    INTERNAL_ERROR,
}

KNOWN_ACTIONS = {
    "build",
    "decode",
    "send",
    "wait-frame",
    "wait_frame",
    "request",
    "wait_log",
    "serial.connect",
    "serial.disconnect",
    "serial.open",
    "serial.close",
    "serial.send",
    "serial.set",
    "serial.ports",
    "auto_rule.add",
    "auto_rule.update",
    "auto_rule.remove",
    "auto_rule.list",
    "auto_rule.show",
    "auto_rule.enable",
    "auto_rule.disable",
    "auto_rule.test",
    "auto_rule.load",
    "auto_rule.history",
    "assert",
    "set_var",
    "sleep",
    "expr",
    "loop",
    "if",
}


@dataclass
class RunError:
    code: str
    message: str
    step_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.step_id:
            out["step_id"] = self.step_id
        if self.details:
            out["details"] = self.details
        return out


def classify_step_failure(
    step_id: str,
    action: str,
    result: dict[str, Any],
    *,
    message: str = "",
) -> RunError:
    error_text = message or str(result.get("error") or result.get("status") or "step failed")
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    lower = error_text.lower()

    if "run timeout" in lower:
        return RunError(RUN_TIMEOUT, error_text, step_id=step_id, details=detail)

    if action in {"wait-frame", "wait_frame", "request"}:
        if "timeout" in lower:
            return RunError(
                WAIT_FRAME_TIMEOUT,
                error_text,
                step_id=step_id,
                details=_diagnostic_details(detail),
            )
        if detail.get("mismatch_summary"):
            return RunError(
                MATCH_FAILED,
                error_text,
                step_id=step_id,
                details=_diagnostic_details(detail),
            )

    if action == "build" or (action == "request" and "build" in lower):
        return RunError(BUILD_FAILED, error_text, step_id=step_id, details=detail)

    if action == "decode":
        return RunError(DECODE_FAILED, error_text, step_id=step_id, details=detail)

    if action.startswith("auto_rule"):
        return RunError(AUTO_RULE_FAILED, error_text, step_id=step_id, details=detail)

    if action.startswith("serial"):
        if "not connected" in lower or "no connection" in lower or "connect" in lower and "fail" in lower:
            return RunError(SERIAL_NOT_CONNECTED, error_text, step_id=step_id, details=detail)
        if "send" in lower or action == "send":
            return RunError(SERIAL_WRITE_FAILED, error_text, step_id=step_id, details=detail)

    if "timeout" in lower:
        return RunError(STEP_TIMEOUT, error_text, step_id=step_id, details=detail)

    return RunError(STEP_FAILED, error_text, step_id=step_id, details=_diagnostic_details(detail))


def classify_exception(step_id: str, action: str, exc: Exception) -> RunError:
    text = str(exc)
    if "run timeout" in text.lower():
        return RunError(RUN_TIMEOUT, text, step_id=step_id)
    from test_runner.variables import VariableError

    if isinstance(exc, VariableError):
        return RunError(PLAN_VAR_UNRESOLVED, text, step_id=step_id)
    return RunError(INTERNAL_ERROR, text, step_id=step_id)


def _diagnostic_details(detail: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("received_frames", "decoded_frames", "timeout_ms", "last_decoded", "mismatch_summary"):
        if key in detail:
            out[key] = detail[key]
    return out


def extract_diagnostics(error: RunError | dict[str, Any] | None) -> dict[str, Any]:
    if error is None:
        return {}
    details = error.details if isinstance(error, RunError) else error.get("details") or {}
    out: dict[str, Any] = {}
    if details.get("last_decoded"):
        out["last_decoded"] = details["last_decoded"]
    if details.get("mismatch_summary"):
        out["mismatch_summary"] = details["mismatch_summary"]
    if details.get("received_frames") is not None:
        out["received_frames"] = details["received_frames"]
    return out
