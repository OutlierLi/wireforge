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
        "description": "TestPlan 结构校验 + 各 build 步骤 route input_schema 校验（不连接串口）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "inline TestPlan"},
                "file": {"type": "string", "description": "TestPlan YAML 文件路径"},
                "vars": {"type": "object", "description": "变量覆盖（用于 build schema 校验）"},
                "skip_build_check": {"type": "boolean", "description": "跳过 build/route schema 校验"},
            },
        },
    },
    {
        "name": "test.dry_run",
        "description": "展开变量、检查 action、build/route schema 校验、生成 resolved_plan，不执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object"},
                "file": {"type": "string"},
                "vars": {"type": "object", "description": "变量覆盖"},
                "skip_build_check": {"type": "boolean", "description": "跳过 build/route schema 校验"},
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
                        "skip_build_check": {"type": "boolean"},
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
            vars=as_object(arguments.get("vars")) if arguments.get("vars") else None,
            skip_build_check=bool(arguments.get("skip_build_check", False)),
        )
    if name == "test.dry_run":
        return RunCommand.dry_run(
            plan=arguments.get("plan"),
            file=arguments.get("file"),
            vars=as_object(arguments.get("vars")) if arguments.get("vars") else None,
            skip_build_check=bool(arguments.get("skip_build_check", False)),
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

## Prerequisites (read first)

**Before writing TestPlan YAML**, use wireforge MCP `protocol_task_run` to confirm every frame's
route and `input_schema` (see repo `AGENTS.md` Build Flow). Stop and ask the user if any
required field is missing. Do not guess build field names.

Then use this test MCP to validate and run the plan.

## Agent workflow

### Phase 0 — protocol MCP (wireforge)

1. List all frames the test needs (downlink, uplink, mock replies)
2. Call `protocol_task_run` for each → get `input_schema` / `required_fields`
3. Stop if unmatched or missing parameters; ask user

### Phase 1 — write YAML

- Copy template: `database/templates/test_plan_mock_auto.yaml`
- Full guide: `database/examples/TEST_PLAN_AGENT.md`
- Minimal example: `database/runs/mock_auto_ack.yaml`

### Phase 2 — test MCP (this server)

1. `test.schema` — template, examples, build_field_types, workflow
2. `test.validate` — YAML structure + **build/route schema check** per build step
3. `test.dry_run` — resolve vars + build schema check on resolved args
4. `test.run` — execute (also runs build check unless `options.skip_build_check`)
5. On failure: `test.read_report` with `step_id`

Build field names must come from protocol MCP `input_schema`. On mismatch, errors include
`unknown_fields`, `missing_required`, and `input_schema` for that step.

## Serial port

- Default in template: `vars.port: mock://auto` (script self-test with auto_rule)
- Real device: pass `options.vars.port` e.g. `/dev/ttyUSB0` or `COM3`

## test.run input

```json
{
  "file": "database/runs/mock_auto_ack.yaml",
  "options": {
    "timeout_ms": 60000,
    "vars": {"port": "/dev/ttyUSB0"}
  }
}
```

## Key conventions

- Build all frames via `build` action; never hand-craft hex
- `send` with `timeout: 0` when followed by `wait-frame`
- `auto_rule.match`: DI hex substring from build output, not `68.*16`
- `auto_rule.then`: dict format with `command` and `args.hex`
- Repeat steps: `action: loop` with `args.over` (list) or `args.count`
- Conditional steps: `action: if` with `args.when` (`eq` / `not` / `all`)
- Arithmetic: `action: expr` or `${qi * 32 + 1}`; count loop without `index_as` auto-injects `i` and `qi`
- Composite vars: `${batches.0.addrs[1]}`, `${device.port}`
- dry_run adds `loop_preview` when loop bounds are statically known (max 32 iterations)

## Protocol sources

- Map: `compiled/protocol_map.yaml` (run `python3 scripts/bootstrap_protocol_cache.py`)
- CSG fields: `protocol_tool/protocols/csg_2016/variants/afn_payloads.yaml`

Reports are written to `log/run_reports/<run_id>/` by default.
"""


if __name__ == "__main__":
    raise SystemExit(main())
