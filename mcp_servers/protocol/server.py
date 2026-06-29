"""Minimal MCP stdio server for WireForge protocol tasks."""

from __future__ import annotations

import sys
from typing import Any, BinaryIO

from agent_protocol import run_agent_protocol
from mcp_servers.common.stdio import (
    as_object,
    jsonrpc_error,
    jsonrpc_result,
    serve as stdio_serve,
    tool_result,
)


SERVER_NAME = "wireforge-protocol-agent"
SERVER_VERSION = "0.1.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "protocol_task_run",
        "description": "推进协议地图驱动的协议任务状态机：BUILD、DECODE、SEND，保存 run_id 状态并返回当前结果。SUCCEEDED 时 final_frame 为完整 hex（不截断）；Agent 必须原样转给用户，禁止 ×N/[CS] 等缩写。",
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
    return stdio_serve(input_stream, output_stream, handle_message)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    if "method" not in message:
        return None
    method = str(message["method"])
    request_id = message.get("id")
    try:
        if method == "initialize":
            params = as_object(message.get("params"))
            protocol_version = str(params.get("protocolVersion") or "2024-11-05")
            return jsonrpc_result(request_id, {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "ping":
            return jsonrpc_result(request_id, {})
        if method == "tools/list":
            return jsonrpc_result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = as_object(message.get("params"))
            name = str(params.get("name") or "")
            arguments = as_object(params.get("arguments"))
            return jsonrpc_result(request_id, tool_result(call_tool(name, arguments)))
        if method == "resources/list":
            return jsonrpc_result(request_id, {"resources": RESOURCES})
        if method == "resources/read":
            params = as_object(message.get("params"))
            uri = str(params.get("uri") or "")
            if uri != "wireforge://usage/protocol-agent":
                raise ValueError(f"unknown resource: {uri}")
            return jsonrpc_result(request_id, {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": _usage_text(),
                }]
            })
        if method in {"resources/templates/list", "prompts/list"}:
            key = "resourceTemplates" if method.startswith("resources/") else "prompts"
            return jsonrpc_result(request_id, {key: []})
        if method.startswith("notifications/"):
            return None
        raise ValueError(f"unsupported MCP method: {method}")
    except Exception as exc:
        return jsonrpc_error(request_id, -32000, str(exc))


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name != "protocol_task_run":
        raise ValueError(f"unknown tool: {name}")
    return run_agent_protocol(
        raw_input=arguments.get("raw_input"),
        run_id=arguments.get("run_id"),
        user_input=as_object(arguments.get("user_input")) if arguments.get("user_input") else None,
        debug=arguments.get("debug") if "debug" in arguments else None,
    )


def _usage_text() -> str:
    return """# WireForge Protocol Agent MCP

Tool: `protocol_task_run`

- New run: pass `raw_input`.
- Resume run: pass `run_id` and optional `user_input`.
- Default responses are compact for route/match steps. Use `debug: true` per call, or `WIREFORGE_MCP_DEBUG=1`, to return full waiting/results/log paths.
- On BUILD/DECODE success, `final_frame` / `decode.frame` are always the complete hex string (never truncated). The Agent must relay them verbatim to the user.
- Build runs first return `need: "protocol_match"` plus compact `candidates`; the Agent selects one candidate and sends `entry_id` or `route_params`.
- When the user provides a source frame hex plus build intent (`source_mode: "from_frame"`), MCP skips protocol_match, decodes the frame, and returns `need: "values"` with `decoded_values`; send `fields` with only overrides (use `{}` to rebuild unchanged).
- MCP then returns `need: "values"` plus field names; the Agent sends `fields`.
- The MCP persists state in `log/agent_protocol_runs/<run_id>/`.
- It calls Build/Decode/Send modules with structured JSON dictionaries, not CLI strings.
- Route selection is deterministic and based on the generated protocol map.
"""


if __name__ == "__main__":
    raise SystemExit(main())
