# WireForge Agent Rules

## When To Use MCP

Use the OpenCode MCP server `wireforge` first for any user request to build, generate, parse, decode, verify, send, modify, or explain a protocol frame.

Call tool `protocol_task_run` and pass the user's original message as `raw_input` unchanged.

The MCP owns protocol context retrieval, task classification, JSON calls to build/decode/send, state persistence, logging, and build-after-decode verification. Do not manually infer AFN, DI, checksum, payload, direction, or protocol fields before MCP.

Only inspect or edit repository files directly when the user is asking to change code, debug implementation, review tests, or update documentation.
