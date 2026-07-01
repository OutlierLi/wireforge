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
SERVER_VERSION = "0.2.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "protocol_extend_run",
        "description": (
            "从 Agent 编写的 C 结构体扩展 CSG 2016 / DLT645-2007 报文变体："
            "解析 C struct → 生成 YAML → 写盘。任务类型可传 protocol，"
            "或从 raw_input / di / func|afn 自动识别。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "已有任务 run_id；新任务可省略。"},
                "raw_input": {"type": "string", "description": "简短说明（新任务必填）。"},
                "user_input": {
                    "type": "object",
                    "description": (
                        "protocol(csg|dlt645), di（必填）, c_struct|c_struct_path（必填）; "
                        "CSG: afn, add; 645: func(默认0x11), dir; pair, resp_c_struct*, variants[]"
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

**C 结构体流水线**（CSG / DLT645 自动识别）：

1. Agent 阅读协议，编写 DI payload C 结构体（见 `tests/fixtures/c_struct/`）
2. 传 `user_input.di`, `c_struct` 或 `c_struct_path`
   - CSG: `afn`, `add`, `dir`
   - DLT645: `func`（默认 0x11）, `dir`（默认 uplink 应答载荷）
   - 或 `protocol: dlt645` / `protocol: csg`
3. 程序：C struct → YAML → `variants/extensions/*.yaml` → compile/map
4. 日志：`log/protocol_extend_runs/<run_id>/`

645 示例：
```json
{
  "raw_input": "扩展 DLT645 读数据应答",
  "user_input": {
    "protocol": "dlt645",
    "func": "0x11",
    "di": "00099999",
    "description": "自定义电能量",
    "c_struct_path": "tests/fixtures/c_struct/dlt645_custom_energy.h"
  }
}
```

成对报文：`pair: true` + `resp_c_struct_path`。
批量：`variants: [{afn, di, c_struct_path, ...}, ...]`。

详见 AGENTS.md Protocol Extend Flow。
"""


if __name__ == "__main__":
    raise SystemExit(main())
