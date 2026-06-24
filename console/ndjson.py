"""protocol-tui.v1 NDJSON transport.

stdout is reserved for protocol JSON. Diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from console.api import cancel_cmd, complete_cmd, continue_cmd, exec_cmd, exec_text
from console.protocol import SCHEMA_VERSION, response_execution_error


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _handle(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema") != SCHEMA_VERSION:
        return response_execution_error(
            f"unsupported schema: {request.get('schema')}",
            {"expected": SCHEMA_VERSION},
        )

    request_type = request.get("type")
    if request_type == "command.execute":
        command = str(request.get("command", "")).strip()
        args = request.get("args") or {}
        if command.startswith("/"):
            return exec_text(command, args)
        return exec_cmd(command, args)

    if request_type == "interaction.continue":
        return continue_cmd(str(request.get("interaction_id", "")), request.get("args") or {})

    if request_type == "interaction.cancel":
        return cancel_cmd(str(request.get("interaction_id", "")))

    if request_type == "command.complete":
        return complete_cmd(
            prefix=str(request.get("prefix", "")),
            command=str(request.get("command", "")),
        )

    return response_execution_error(f"unknown request type: {request_type}")


def run() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            _write(_handle(request))
        except Exception as exc:
            print(f"wireforge ndjson error: {exc}", file=sys.stderr)
            _write(response_execution_error(str(exc)))


if __name__ == "__main__":
    run()
