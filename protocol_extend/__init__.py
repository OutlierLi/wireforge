"""Protocol variant extension workflow for MCP agents."""

from __future__ import annotations

from typing import Any


def run_protocol_extend(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from protocol_extend.state_machine import run_protocol_extend as _run_protocol_extend

    return _run_protocol_extend(*args, **kwargs)

__all__ = ["run_protocol_extend"]
