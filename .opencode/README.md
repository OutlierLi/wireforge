# .opencode

OpenCode project configuration for WireForge.

MCP servers are configured in `opencode.json`:

## wireforge (protocol)

- name: `wireforge`
- command: `python3 scripts/python/wireforge_mcp_server.py`
- tool: `protocol_task_run`

## wireforge-test (TestPlan)

- name: `wireforge-test`
- command: `python3 scripts/python/wireforge_test_mcp_server.py`
- tools: `test.schema`, `test.validate`, `test.dry_run`, `test.run`, `test.read_report`

Restart OpenCode after changing this file so the MCP registry is reloaded.
