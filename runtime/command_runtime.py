"""Command runtime facade — delegates to console.runtime."""

from __future__ import annotations

from typing import Any

from console.runtime import runtime


def execute(command: str, args: dict[str, Any]) -> dict[str, Any]:
    return runtime.execute(command, args)
