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
            "从 DOCX 自动扩展 CSG 2016 报文变体：解析文档 → 提取字段 → 推断 YAML → 写盘。"
            "关键阶段写入 log/protocol_extend_runs/<run_id>/extend.log 与 stages/。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "已有任务 run_id；新任务可省略。"},
                "raw_input": {"type": "string", "description": "简短说明（新任务必填）。"},
                "user_input": {
                    "type": "object",
                    "description": "document_path（必填）, chapter_hint（可选）",
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

**DOCX 自动流水线**（无手动补参、无用户审阅）：

1. 传 `user_input.document_path`（`.docx`）
2. 程序：解析 DOCX → 批量提取 DI/字段 → TypeInferencer → 写 `variants/extensions/*.yaml`
3. 各阶段关键信息写入 `log/protocol_extend_runs/<run_id>/`：
   - `extend.log` — 文本摘要
   - `stages/*.json` — document_parse / document_extract / inference / yaml_preview / fidelity / draft_result
   - `extracted_drafts.json` — 从文档提取的原始字段
   - `draft_NNN_<DI>_preview.yaml` — 每条推断 YAML

返回 `SUCCEEDED` + `batch_summary`；失败见 `log_dir` 与 `extend.log`。

Install: `pip install python-docx` or `pip install -e ".[doc]"`.

TypeInferencer: 提供 evidence（取值表/单位）；bool 语义 → YAML `enum`；详见 AGENTS.md。
"""


if __name__ == "__main__":
    raise SystemExit(main())
