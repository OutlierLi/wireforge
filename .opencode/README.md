# .opencode

OpenCode project configuration for WireForge.

MCP servers are configured in `opencode.json`:

## wireforge (protocol)

- name: `wireforge`
- command: `python3 scripts/python/wireforge_mcp_server.py`
- tool: `protocol_task_run`

## wireforge-test (TestPlan 编排校验)

- name: `wireforge-test`
- command: `python3 scripts/python/wireforge_test_mcp_server.py`
- tools: `test.schema`, `test.validate`, `test.dry_run`, `test.read_report`

## wireforge-exec-test (真实串口执行)

- name: `wireforge-exec-test`
- command: `python3 scripts/python/wireforge_exec_test_mcp_server.py`
- tools: `exec_test.schema`, `exec_test.run`, `exec_test.read_report`

## wireforge-extend (协议扩展)

- name: `wireforge-extend`
- command: `python3 scripts/python/wireforge_extend_mcp_server.py`
- tool: `protocol_extend_run`

Restart OpenCode after changing this file so the MCP registry is reloaded.
