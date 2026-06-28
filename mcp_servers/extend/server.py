"""MCP stdio server for CSG protocol variant extensions."""

from __future__ import annotations

import sys
from typing import Any, BinaryIO

from protocol_extend import run_protocol_extend
from mcp_servers.common.stdio import (
    as_object,
    jsonrpc_error,
    jsonrpc_result,
    serve as stdio_serve,
    tool_result,
)


SERVER_NAME = "wireforge-protocol-extend"
SERVER_VERSION = "0.1.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "protocol_extend_run",
        "description": (
            "扩展 CSG 2016 报文变体：将自然语言/结构化输入转为 variants/extensions/*.yaml，"
            "缺 dir/add 等参数时 WAITING_INPUT；确认后 compile 校验。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "已有任务 run_id；新任务可省略。"},
                "raw_input": {"type": "string", "description": "自然语言描述扩展报文（新任务必填）。"},
                "user_input": {
                    "type": "object",
                    "description": (
                        "补参或确认：protocol, afn, di, description, dir, add, fields, pair, confirm"
                    ),
                },
                "debug": {
                    "type": "boolean",
                    "description": "返回完整 state；默认 compact。",
                },
            },
        },
    }
]

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "wireforge://usage/protocol-extend",
        "name": "WireForge protocol extend MCP usage",
        "description": "扩展报文 MCP 调用说明。",
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
            if uri != "wireforge://usage/protocol-extend":
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
    if name != "protocol_extend_run":
        raise ValueError(f"unknown tool: {name}")
    return run_protocol_extend(
        raw_input=arguments.get("raw_input"),
        run_id=arguments.get("run_id"),
        user_input=as_object(arguments.get("user_input")) if arguments.get("user_input") else None,
        debug=arguments.get("debug") if "debug" in arguments else None,
    )


def _usage_text() -> str:
    return """# WireForge Protocol Extend MCP

Tool: `protocol_extend_run`

- New run: pass `raw_input` (natural language or structured hints).
- Resume: pass `run_id` + `user_input` to supply missing `dir`, `add`, `fields`, or `confirm`.
- Extensions write to `protocol_tool/protocols/csg_2016/variants/extensions/*.yaml` only.
- v1 supports AFN 00–07 new DI; AFN 08+ requires manual router in protocol.yaml.
- Field DSL supports scalar, struct, and array (count_ref + item_type struct/bcd/...).
- After success, map json+yaml are refreshed automatically; check map_ok and route_entries.

Flow: missing params → `need: params` → preview → `need: confirm` → write + compile + map → `SUCCEEDED`.
See AGENTS.md Protocol Extend Flow for examples.
"""


if __name__ == "__main__":
    raise SystemExit(main())
