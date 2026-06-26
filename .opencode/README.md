# .opencode

OpenCode project configuration for WireForge.

The MCP server is configured in `opencode.json`:

- name: `wireforge`
- command: `python3 scripts/python/wireforge_mcp_server.py`
- tool: `protocol_task_run`

Restart OpenCode after changing this file so the MCP registry is reloaded.
