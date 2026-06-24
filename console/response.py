"""统一响应格式 — 所有 handler 共用。"""

from typing import Any


def ok(data: dict[str, Any] | None = None) -> dict:
    return {"success": True, "data": data or {}}


def fail(error: str, detail: dict[str, Any] | None = None) -> dict:
    return {"success": False, "error": error, "detail": detail or {}}


def missing_param(key: str, type: str = "str",
                  examples: list | None = None,
                  desc: str = "",
                  note: str = "") -> dict:
    """参数缺失的统一错误响应。"""
    m = {"key": key, "type": type}
    if examples: m["examples"] = examples
    if desc: m["desc"] = desc
    if note: m["note"] = note
    return {
        "success": False,
        "error": "missing required parameter",
        "detail": {"missing": [m]},
    }
