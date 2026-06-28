"""Shared MCP stdio framing and JSON-RPC helpers."""

from __future__ import annotations

import json
from typing import Any, BinaryIO, Callable

_FRAMING_MODE = "content-length"


def serve(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    handle_message: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> int:
    global _FRAMING_MODE
    _FRAMING_MODE = "content-length"
    while True:
        message = read_message(input_stream)
        if message is None:
            return 0
        response = handle_message(message)
        if response is not None:
            write_message(output_stream, response)


def tool_result(result: Any) -> dict[str, Any]:
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result, ensure_ascii=False, indent=2),
        }],
        "isError": False,
    }


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    global _FRAMING_MODE
    first = stream.readline()
    if not first:
        return None
    stripped = first.strip()
    if stripped.startswith(b"{"):
        _FRAMING_MODE = "json-lines"
        return json.loads(stripped.decode("utf-8"))
    if first.lower().startswith(b"content-length:"):
        _FRAMING_MODE = "content-length"
        length = int(first.split(b":", 1)[1].strip())
        while True:
            line = stream.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        body = stream.read(length)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))
    return json.loads(stripped.decode("utf-8"))


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _FRAMING_MODE == "json-lines":
        stream.write(body + b"\n")
    else:
        stream.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    stream.flush()


def jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def as_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
