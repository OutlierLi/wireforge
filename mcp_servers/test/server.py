"""MCP stdio server for WireForge TestPlan execution."""

from __future__ import annotations

import sys
from typing import Any, BinaryIO

from mcp_servers.common.stdio import (
    as_object,
    jsonrpc_error,
    jsonrpc_result,
    serve as stdio_serve,
    tool_result,
)
from test_runner.run_command import RunCommand, RunOptions


SERVER_NAME = "wireforge-test-agent"
SERVER_VERSION = "0.1.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "test.schema",
        "description": "返回 TestPlan schema、支持的 action 及字段说明。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "test.validate",
        "description": "只做 TestPlan 结构校验，不连接串口。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "inline TestPlan"},
                "file": {"type": "string", "description": "TestPlan YAML 文件路径"},
            },
        },
    },
    {
        "name": "test.dry_run",
        "description": "展开变量、检查 action、生成 resolved_plan，不执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object"},
                "file": {"type": "string"},
                "vars": {"type": "object", "description": "变量覆盖"},
            },
        },
    },
    {
        "name": "test.run",
        "description": "执行 TestPlan 测试，返回紧凑摘要；完整日志落盘到 report_dir。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "inline TestPlan"},
                "file": {"type": "string", "description": "TestPlan YAML 文件路径"},
                "options": {
                    "type": "object",
                    "properties": {
                        "dry_run": {"type": "boolean"},
                        "timeout_ms": {"type": "integer"},
                        "report_root": {"type": "string"},
                        "stop_on_error": {"type": "boolean"},
                        "vars": {"type": "object"},
                        "report": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "test.read_report",
        "description": "按 report_dir 读取摘要、失败 step 诊断、最近帧。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_dir": {"type": "string", "description": "报告目录路径或 run_id"},
                "run_id": {"type": "string", "description": "run_id（在 log/run_reports 下查找）"},
                "step_id": {"type": "string", "description": "指定 step 诊断"},
                "tail_frames": {"type": "integer", "description": "最近帧行数，默认 20"},
            },
        },
    },
]

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "wireforge://usage/test-agent",
        "name": "WireForge test agent MCP usage",
        "description": "TestPlan MCP 的边界和调用说明。",
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
            if uri != "wireforge://usage/test-agent":
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
    if name == "test.schema":
        return RunCommand.schema()
    if name == "test.validate":
        return RunCommand.validate(
            plan=arguments.get("plan"),
            file=arguments.get("file"),
        )
    if name == "test.dry_run":
        return RunCommand.dry_run(
            plan=arguments.get("plan"),
            file=arguments.get("file"),
            vars=as_object(arguments.get("vars")) if arguments.get("vars") else None,
        )
    if name == "test.run":
        return RunCommand.run(
            plan=arguments.get("plan"),
            file=arguments.get("file"),
            options=as_object(arguments.get("options")) if arguments.get("options") else None,
        )
    if name == "test.read_report":
        report_dir = arguments.get("report_dir") or arguments.get("run_id")
        if not report_dir:
            raise ValueError("report_dir or run_id is required")
        return RunCommand.read_report(
            str(report_dir),
            step_id=arguments.get("step_id"),
            tail_frames=int(arguments.get("tail_frames") or 20),
        )
    raise ValueError(f"unknown tool: {name}")


def _usage_text() -> str:
    return """# WireForge Test Agent MCP

Tools: `test.schema`, `test.validate`, `test.dry_run`, `test.run`, `test.read_report`

## Agent workflow

1. Generate TestPlan
2. `test.validate` — fix schema errors
3. `test.dry_run` — fix variable/action errors
4. `test.run` — execute; read compact summary
5. On failure: `test.read_report` with `step_id` for diagnostics

## test.run input

Inline plan or file path, plus optional options:

```json
{
  "file": "database/runs/all_actions.yaml",
  "options": {"timeout_ms": 120000, "dry_run": false}
}
```

Reports are written to `log/run_reports/<run_id>/` by default.
"""


if __name__ == "__main__":
    raise SystemExit(main())
