"""Minimal MCP stdio server for WireForge protocol tasks."""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from agent_protocol import run_agent_protocol


SERVER_NAME = "wireforge-protocol-agent"
SERVER_VERSION = "0.1.0"
_FRAMING_MODE = "content-length"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "protocol_task_run",
        "description": "推进协议地图驱动的协议任务状态机：BUILD、DECODE、SEND，保存 run_id 状态并返回当前结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "已有任务 run_id；新任务可省略。"},
                "raw_input": {"type": "string", "description": "用户原始输入；新任务必填，会永久保存。"},
                "user_input": {
                    "type": "object",
                    "description": "WAITING_INPUT 后用户补充的结构化字段，如 {\"entry_id\":\"...\"} 或 {\"fields\":{...}}。",
                },
                "debug": {
                    "type": "boolean",
                    "description": "返回完整调试结构；默认 false。也可用 WIREFORGE_MCP_DEBUG=1 全局开启。",
                },
            },
        },
    }
]

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "wireforge://usage/protocol-agent",
        "name": "WireForge protocol agent MCP usage",
        "description": "自然语言协议任务 MCP 的边界和调用说明。",
        "mimeType": "text/markdown",
    }
]


def main() -> int:
    return serve(sys.stdin.buffer, sys.stdout.buffer)


def serve(input_stream: BinaryIO, output_stream: BinaryIO) -> int:
    global _FRAMING_MODE
    _FRAMING_MODE = "content-length"
    while True:
        message = _read_message(input_stream)
        if message is None:
            return 0
        response = handle_message(message)
        if response is not None:
            _write_message(output_stream, response)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    if "method" not in message:
        return None
    method = str(message["method"])
    request_id = message.get("id")
    try:
        if method == "initialize":
            params = _object(message.get("params"))
            protocol_version = str(params.get("protocolVersion") or "2024-11-05")
            return _result(request_id, {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = _object(message.get("params"))
            name = str(params.get("name") or "")
            arguments = _object(params.get("arguments"))
            return _result(request_id, _tool_result(call_tool(name, arguments)))
        if method == "resources/list":
            return _result(request_id, {"resources": RESOURCES})
        if method == "resources/read":
            params = _object(message.get("params"))
            uri = str(params.get("uri") or "")
            if uri != "wireforge://usage/protocol-agent":
                raise ValueError(f"unknown resource: {uri}")
            return _result(request_id, {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": _usage_text(),
                }]
            })
        if method in {"resources/templates/list", "prompts/list"}:
            key = "resourceTemplates" if method.startswith("resources/") else "prompts"
            return _result(request_id, {key: []})
        if method.startswith("notifications/"):
            return None
        raise ValueError(f"unsupported MCP method: {method}")
    except Exception as exc:
        return _error(request_id, -32000, str(exc))


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name != "protocol_task_run":
        raise ValueError(f"unknown tool: {name}")
    return run_agent_protocol(
        raw_input=arguments.get("raw_input"),
        run_id=arguments.get("run_id"),
        user_input=_object(arguments.get("user_input")) if arguments.get("user_input") else None,
        debug=arguments.get("debug") if "debug" in arguments else None,
    )


def _tool_result(result: Any) -> dict[str, Any]:
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result, ensure_ascii=False, indent=2),
        }],
        "isError": False,
    }


def _usage_text() -> str:
    return """# WireForge Protocol Agent MCP

Tool: `protocol_task_run`

- New run: pass `raw_input`.
- Resume run: pass `run_id` and optional `user_input`.
- Default responses are compact. Use `debug: true` per call, or `WIREFORGE_MCP_DEBUG=1`, to return full waiting/results/log paths.
- Build runs first return `need: "protocol_match"` plus compact `candidates`; the Agent selects one candidate and sends `entry_id` or `route_params`.
- MCP then returns `need: "values"` plus field names; the Agent sends `fields`.
- The MCP persists state in `log/agent_protocol_runs/<run_id>/`.
- It calls Build/Decode/Send modules with structured JSON dictionaries, not CLI strings.
- Route selection is deterministic and based on the generated protocol map.
"""


def _read_message(stream: BinaryIO) -> dict[str, Any] | None:
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


def _write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _FRAMING_MODE == "json-lines":
        stream.write(body + b"\n")
    else:
        stream.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    stream.flush()


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
