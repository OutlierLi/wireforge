"""MCP stdio server for WireForge execution TestPlan runs (real serial)."""

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
from test_runner.exec_command import ExecCommand


SERVER_NAME = "wireforge-exec-test-agent"
SERVER_VERSION = "0.1.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "exec_test.schema",
        "description": "执行测试 schema、报告模版字段、workflow（编排校验请用 test MCP）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "exec_test.run",
        "description": "真实串口执行 TestPlan（等同 CLI /run，禁止 dry_run），支持 vars 覆盖；成功/失败均生成 execution_report。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "inline TestPlan"},
                "file": {"type": "string", "description": "TestPlan YAML 路径"},
                "options": {
                    "type": "object",
                    "properties": {
                        "timeout_ms": {"type": "integer"},
                        "report_root": {"type": "string", "description": "默认 log/exec_reports"},
                        "stop_on_error": {"type": "boolean"},
                        "vars": {"type": "object", "description": "变量覆盖，如 port/conn/baudrate"},
                        "report": {"type": "string", "description": "自定义报告目录"},
                        "skip_build_check": {"type": "boolean"},
                    },
                },
            },
        },
    },
    {
        "name": "exec_test.read_report",
        "description": "读取 execution_report.json（含串口 trace、错误分析、测试目的/预期/流程）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_dir": {"type": "string"},
                "run_id": {"type": "string"},
                "step_id": {"type": "string"},
                "format": {"type": "string", "enum": ["full", "compact"], "description": "默认 full"},
            },
        },
    },
]

RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "wireforge://usage/exec-test-agent",
        "name": "WireForge execution test MCP usage",
        "description": "真实串口执行测试 MCP 调用说明。",
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
            if uri != "wireforge://usage/exec-test-agent":
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
    if name == "exec_test.schema":
        return ExecCommand.schema()
    if name == "exec_test.run":
        return ExecCommand.run(
            plan=arguments.get("plan"),
            file=arguments.get("file"),
            options=as_object(arguments.get("options")) if arguments.get("options") else None,
        )
    if name == "exec_test.read_report":
        report_dir = arguments.get("report_dir") or arguments.get("run_id")
        if not report_dir:
            raise ValueError("report_dir or run_id is required")
        return ExecCommand.read_report(
            str(report_dir),
            step_id=arguments.get("step_id"),
            format=str(arguments.get("format") or "full"),
        )
    raise ValueError(f"unknown tool: {name}")


def _usage_text() -> str:
    return """# WireForge Execution Test MCP

**与 wireforge-test MCP 分工**

| MCP | 用途 |
|-----|------|
| **wireforge-test** (`test.validate` / `test.dry_run`) | 编排校验、变量展开、build schema 检查（不连串口） |
| **wireforge-exec-test** (本服务) | **真实串口发送/接收**，生成结构化执行报告 |

Tools: `exec_test.schema`, `exec_test.run`, `exec_test.read_report`

## 前置

1. Phase 0: `protocol_task_run` 确认每条报文 schema
2. `test.validate` → `test.dry_run` 通过后再执行
3. YAML 建议填写 `purpose` / `expected_results` / `test_flow`（写入报告）

模版: `database/templates/execution_test_plan.yaml`

## exec_test.run

等同 CLI `/run`，**禁止 dry_run**，默认报告目录 `log/exec_reports/`。

```json
{
  "file": "database/runs/mock_auto_ack.yaml",
  "options": {
    "timeout_ms": 120000,
    "vars": {
      "port": "/dev/ttyUSB0",
      "conn": "cco",
      "baudrate": 9600
    }
  }
}
```

成功或失败均生成:
- `execution_report.json` — 机器可读（含 serial_trace、error_analysis）
- `execution_report.md` — 人类可读报告模版
- 以及 `report.json`, `frames.log`, `timeline.log` 等

## exec_test.read_report

```json
{"report_dir": "log/exec_reports/mock_auto_ack_20260629_120000", "format": "compact"}
```

## 报告内容

- 测试目的 / 预期结果 / 测试流程（来自 plan 顶层字段）
- 串口收发记录 `serial_trace[]`（TX/RX hex、解码）
- 步骤执行结果
- 失败时 `error_analysis`（错误码、诊断、排查建议）
"""


if __name__ == "__main__":
    raise SystemExit(main())
