"""MCP stdio server for protocol variant extensions."""

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
SERVER_VERSION = "0.3.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "protocol_extend_run",
        "description": (
            "Extend CSG 2016 / DLT645-2007 variants from Agent-authored "
            "payload schema fields into YAML. Protocol can be supplied or "
            "auto-detected from raw_input / di / func|afn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Existing run id; omit for a new task."},
                "raw_input": {"type": "string", "description": "Brief task description, required for new runs."},
                "user_input": {
                    "type": "object",
                    "description": (
                        "protocol(csg|dlt645), di, fields|empty_payload; "
                        "CSG: afn, add; DLT645: func(default 0x11), dir; "
                        "pair, resp_fields|resp_empty_payload, variants[]."
                    ),
                },
                "debug": {
                    "type": "boolean",
                    "description": "Return full state instead of compact output.",
                },
            },
        },
    }
]

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "wireforge://usage/protocol-extend",
        "name": "WireForge protocol extend MCP usage",
        "description": "Protocol extension MCP usage.",
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

Schema-to-YAML pipeline for CSG / DLT645 extension variants.

1. Agent reads the protocol text and writes payload schema fields.
2. Pass `user_input.di` plus `fields` or `empty_payload`.
   - CSG: `afn`, `add`, `dir`
   - DLT645: `func` default `0x11`, `dir` defaults by func
   - Pair messages: `pair: true` plus `resp_fields` or `resp_empty_payload`
3. WireForge writes `variants/extensions/*.yaml`, compiles, and refreshes the protocol map.
4. Logs are under `log/protocol_extend_runs/<run_id>/`.

DLT645 example:
```json
{
  "raw_input": "extend DLT645 read data response",
  "user_input": {
    "protocol": "dlt645",
    "func": "0x11",
    "di": "00099999",
    "description": "custom energy",
    "fields": [
      {"name": "rate_index", "type": "uint8", "desc": "rate index"},
      {"name": "energy_raw", "type": "uint32_le", "desc": "raw energy"}
    ]
  }
}
```
"""


if __name__ == "__main__":
    raise SystemExit(main())
