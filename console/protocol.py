"""protocol-tui.v1 — Python command-runtime 与前端通信契约。

请求:
  command.execute   → 执行新命令
  interaction.continue → 继续多轮交互
  interaction.cancel   → 取消交互
  command.complete  → 请求命令/参数补全

响应:
  success            → 执行成功，附带 data
  need_input         → 需要补充参数，附带 input_schema
  need_disambiguation → 多条路径可选，附带 candidates
  invalid_argument   → 参数非法，附带 detail
  no_route           → 路径不存在
  execution_error    → 执行异常
  session.closed     → 会话结束

事件:
  output.append      → 追加语义输出
  progress.update    → 更新进度
  session.closed     → 会话结束

传输: stdin/stdout NDJSON，每行一条完整 JSON。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "protocol-tui.v1"

ResponseKind = Literal[
    "success", "need_input", "need_disambiguation",
    "invalid_argument", "no_route", "execution_error",
    "session_closed", "route_required",
]


@dataclass
class Interaction:
    """多轮交互状态 — 由 runtime 持有。"""
    id: str
    command: str
    args: dict[str, Any] = field(default_factory=dict)
    step: int = 0


# ── 请求 ──────────────────────────────────────────────────────────────

def request_execute(command: str, args: dict[str, Any]) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "type": "command.execute",
        "command": command,
        "args": args,
    }


def request_continue(interaction_id: str, args: dict[str, Any]) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "type": "interaction.continue",
        "interaction_id": interaction_id,
        "args": args,
    }


def request_cancel(interaction_id: str) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "type": "interaction.cancel",
        "interaction_id": interaction_id,
    }


def request_complete(prefix: str = "", command: str = "") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "type": "command.complete",
        "prefix": prefix,
        "command": command,
    }


# ── 响应 ──────────────────────────────────────────────────────────────

def response_success(data: dict[str, Any] | None = None,
                     interaction_id: str = "",
                     interaction_closed: bool = False) -> dict:
    r: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "status": "success",
    }
    if data: r["data"] = data
    if interaction_id: r["interaction_id"] = interaction_id
    if interaction_closed: r["interaction_closed"] = True
    return r


def response_need_input(interaction_id: str,
                        input_schema: list[dict],
                        hint: str = "") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": "need_input",
        "interaction_id": interaction_id,
        "input_schema": input_schema,
        "hint": hint,
    }


def response_need_disambiguation(candidates: list[dict],
                                 key: str = "",
                                 hint: str = "") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": "need_disambiguation",
        "key": key,
        "candidates": candidates,
        "hint": hint,
    }


def response_invalid_argument(key: str, expected: str, got: Any = None,
                              hint: str = "") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": "invalid_argument",
        "detail": {
            "key": key,
            "expected": expected,
            "got": str(got) if got is not None else None,
            "hint": hint,
        },
    }


def response_no_route(error: str, path: str = "") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": "no_route",
        "error": error,
        "path": path,
    }


def response_execution_error(error: str, detail: dict | None = None) -> dict:
    r: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "status": "execution_error",
        "error": error,
    }
    if detail: r["detail"] = detail
    return r


def response_session_closed(interaction_id: str) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "status": "session_closed",
        "interaction_id": interaction_id,
    }


# ── 事件 ──────────────────────────────────────────────────────────────

def event_output_append(text: str, token: str = "text",
                        copy_text: str | None = None) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "event": "output.append",
        "payload": {
            "text": text,
            "token": token,
            "copyText": text if copy_text is None else copy_text,
        },
    }


def event_progress_update(current: int, total: int | None = None,
                          label: str = "") -> dict:
    payload: dict[str, Any] = {"current": current}
    if total is not None:
        payload["total"] = total
    if label:
        payload["label"] = label
    return {
        "schema": SCHEMA_VERSION,
        "event": "progress.update",
        "payload": payload,
    }
