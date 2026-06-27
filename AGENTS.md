# WireForge Agent Rules

Use the MCP tool `protocol_task_run` for natural-language protocol build/decode/send tasks.

Before protocol tasks, the repository must be initialized once:

```bash
python3 scripts/bootstrap_protocol_cache.py
```

This clears old generated outputs, compiles protocol IR files, generates route SVGs, and writes `compiled/protocol_map.json`. The Agent must not generate the protocol map during a user task. If MCP returns a missing-cache error, tell the user to run the bootstrap command above.

## Build Flow

1. Call MCP with the user text:

```json
{"raw_input":"构造一个请求集中器的响应报文，时间为当前时间"}
```

2. MCP returns compact output: `state: "WAITING_INPUT"`, `need: "protocol_match"`, `map_entries`, and `candidates`, not the full map.

3. Match the user text to exactly one candidate entry by its `description`, `name`, `path`, `fields`, and route parameters.

If no entry matches, stop and tell the user: `未识别的报文，请补充协议地图描述。`

If several entries share the same `leaf_id`, do not use the leaf id. Choose the full path-level `entry_id` that includes `dir`, `add`, `afn`, `di`, or stop and ask the user to clarify direction/address.

4. Resume MCP with the selected entry:

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "entry_id": "node:csg_2016.csg_2016.afn06_request_time_resp::dir=uplink::add=0::afn=06::di=E8060601",
    "route_params": {"proto":"csg","afn":"06","di":"E8060601","dir":"uplink"}
  }
}
```

5. MCP calls `/route` and returns `need: "values"` plus `fields`.

6. Fill `fields` from the user text and deterministic context. If a value is missing, ask the user instead of guessing.

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "fields": {
      "datetime.second": "06",
      "datetime.minute": "49",
      "datetime.hour": "21",
      "datetime.day": "26",
      "datetime.month": "06",
      "datetime.year": "26"
    }
  }
}
```

7. MCP executes `/build`, then `/decode` verification.

If build fails, MCP returns `WAITING_INPUT` with the build error. Rebuild fields and retry. After 3 build failures, MCP returns `FAILED`; report the failure to the user.

For troubleshooting only, pass `"debug": true` in the tool call or start the MCP server with `WIREFORGE_MCP_DEBUG=1`. Debug mode returns full `waiting_input`, `results`, and log paths; default mode should stay compact.

## Decode Flow

For complete HEX decode requests, call MCP once with `raw_input`. MCP may detect the protocol and return `SUCCEEDED`.

## Rules

- Do not call CLI commands from the Agent for protocol work.
- Route selection must come from `protocol_map`.
- MCP owns state transitions, logging, route calls, build calls, decode verification, and retry counting.
- Agent owns natural-language matching and value construction from returned schemas.
