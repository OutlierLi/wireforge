# WireForge Agent Rules

Use the MCP tool `protocol_task_run` for natural-language protocol build/decode/send tasks.

Use the MCP tool `protocol_extend_run` to add CSG 2016 variant extensions (new DI under AFN 00–07) into `variants/extensions/` without editing `afn_payloads.yaml`. Start with:

```bash
wireforge-extend-mcp-server
# or
python3 scripts/python/wireforge_extend_mcp_server.py
```

Use the **编排校验** test MCP tools (`test.schema`, `test.validate`, `test.dry_run`, `test.read_report`) for YAML TestPlan validation. Start with:

```bash
wireforge-test-mcp-server
# or
python3 scripts/python/wireforge_test_mcp_server.py
```

Use the **真实串口执行** exec test MCP (`exec_test.schema`, `exec_test.run`, `exec_test.read_report`) after validate/dry_run pass. Start with:

```bash
wireforge-exec-test-mcp-server
# or
python3 scripts/python/wireforge_exec_test_mcp_server.py
```

## Test MCP Flow（编排校验，不连串口）

1. Agent generates a TestPlan (version 1, name, steps); execution plans should include `purpose`, `expected_results`, `test_flow` (see [`database/templates/execution_test_plan.yaml`](database/templates/execution_test_plan.yaml)).
2. Call `test.validate` with inline `plan` or `file` — fix schema/action errors; each `build` step is checked against `/route` `input_schema` (`build_checks`, `PLAN_BUILD_SCHEMA_MISMATCH` on mismatch).
3. Call `test.dry_run` — resolve variables and re-check build args against route schema (stricter than validate alone).
4. On failure during dry_run, call `test.read_report` if a prior run exists.

Call `test.schema` for `build_field_types` (how to pass bcd/array/struct in YAML) and `workflow` order.

## Execution Test MCP Flow（真实串口执行）

After `test.validate` + `test.dry_run` pass:

1. Call `exec_test.run` with `file` or `plan` and `options.vars` (e.g. `port: /dev/ttyUSB0`).
2. Read `ok` / `status` / `report_dir` from the result; **success or fail** both write `execution_report.json` + `execution_report.md` under `log/exec_reports/<run_id>/`.
3. Call `exec_test.read_report` with `report_dir` for serial trace, error analysis, purpose/expected_results.

`exec_test.run` is equivalent to CLI `/run` (no dry_run). `test.run` remains for quick mock self-tests only.

## TestPlan 编排工作流

编写 TestPlan 前必须先走 **protocol MCP**（`protocol_task_run`），再走 **test MCP**。详细说明见 [`database/examples/TEST_PLAN_AGENT.md`](database/examples/TEST_PLAN_AGENT.md)。

### 两个 MCP 的分工

| 阶段 | MCP | 职责 |
|------|-----|------|
| Phase 0 — 编排前 | wireforge `protocol_task_run` | 逐条报文匹配路由、取 `input_schema`、确认必填/默认/推导字段 |
| Phase 1 — 编写 YAML | （Agent） | 从 [`database/templates/execution_test_plan.yaml`](database/templates/execution_test_plan.yaml) 复制，填写 purpose/expected_results/test_flow |
| Phase 2 — 编排校验 | wireforge-test `test.validate` … `test.dry_run` | 结构/build schema/变量展开（**不连串口**） |
| Phase 3 — 真实执行 | wireforge-exec-test `exec_test.run` | 串口真实收发；报告 `log/exec_reports/` |

**Build Flow 不仅是单次构帧，也是 TestPlan 编排的前置依赖分析** — 禁止跳过 protocol MCP 直接写 YAML 或猜测 build 字段名。

### Phase 0：依赖清单与退出规则

1. 列出测试涉及的所有报文（下行、上行、mock 规则帧）
2. 对每条调用 `protocol_task_run`（见下方 Build Flow）
3. 对照 `required_fields`；缺匹配或缺参则**停止**，向用户展示参数表并索要输入
4. 全部确认后再编写 TestPlan

| 情况 | 行为 |
|------|------|
| 无 candidate | `未识别的报文，请补充协议地图描述。` |
| 同 leaf_id 多 entry | 请用户澄清 dir/add |
| required_fields 缺失 | 展示参数表，停止编排 |
| protocol_map 缺失 | 提示运行 bootstrap |

### 串口变量

```yaml
vars:
  port: mock://auto   # 默认虚拟串口，验证脚本逻辑
```

真机：`test.run` 传 `"options": {"vars": {"port": "/dev/ttyUSB0"}}`（或 `COM3`）。

### TestPlan 铁律

- 报文一律 `build` 构造，禁止手拼 hex
- `send` 后接 `wait-frame` 时 `timeout: 0`
- `auto_rule.match` 用 build 下行帧的 DI hex 片段，不用宽泛 regex
- 重复步骤用 `loop`，分支用 `if`（见 TEST_PLAN_AGENT.md）
- 数组/结构体 vars 用 `${batch.addrs.0}`、`${device.port}` 访问
- 算术用 `expr` action 或 `${qi * 32}`；`count` loop 未写 `index_as` 时自动注入 `i`/`qi`

- 模版：[`database/templates/test_plan_mock_auto.yaml`](database/templates/test_plan_mock_auto.yaml)
- loop/if 示例：[`database/runs/loop_batch_demo.yaml`](database/runs/loop_batch_demo.yaml)

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

5. MCP calls `/route` and returns `need: "values"` plus the full parameter schema.

When `need` is `"values"`, read these fields from the MCP result:

- `input_schema`: all parameters, including `name`, `type`, `required`, `desc`, `length`, and optional `default`.
- `required_fields`: fields that must be filled by the Agent or user.
- `defaulted_fields`: fields MCP/build will fill from deterministic defaults.
- `derived_fields`: fields MCP/build will compute from other fields.

When asking the user for missing values, do not only list `fields`. Show a concise parameter table with all parameters:

```text
需要补充的参数：
- address_area.adst | bcd(6) | 必填 | 目的地址
- payload           | hex    | 必填 | 原始报文内容

已使用默认值：
- address_area.asrc | bcd(6)    | 默认 000000000000 | 源地址
- task_id           | uint16_le | 默认 0            | 任务ID
- task_mode_word    | uint8     | 默认 16           | 任务模式字
- timeout_seconds   | uint16_le | 默认 70           | 任务执行超时时间(秒)

自动推导：
- payload_length = byte_length(payload)
```

If `input_schema` is present, it is authoritative. Use it to explain parameter names, descriptions, data types, defaults, and whether each value is required.

6. Fill `required_fields` from the user text and deterministic context. Use `input_schema` to validate names and types. Do not ask the user for values listed in `defaulted_fields` or `derived_fields` unless the user explicitly wants to override a default. If a required value is missing, ask the user and include the full parameter table described above.

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

## From-Frame Build Flow

Use this when the user wants to **construct a new frame from an existing hex frame** (modify a few fields or rebuild unchanged). MCP detects `BUILD` intent plus a frame-like hex in `raw_input` (or `user_input.from_frame`).

This path **skips** `protocol_match` — route and defaults come from decoding the source frame.

1. Call MCP with source frame embedded in natural language:

```json
{"raw_input": "根据旧报文修改 freeze_year，源报文 FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"}
```

2. MCP returns `state: "WAITING_INPUT"`, `need: "values"`, `source_mode: "from_frame"`, plus `input_schema` and compact `decoded_values`.

3. Resume with field overrides only (empty object rebuilds the same frame):

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "fields": {
      "freeze_year": "27"
    }
  }
}
```

One-shot (same turn):

```json
{
  "raw_input": "根据旧报文重建 FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
  "user_input": {"fields": {}}
}
```

4. MCP runs `/build --from-frame` internally, then decode verification. Success returns `final_frame` and `decode_verified`.

If decode fails (invalid or unrecognized frame), MCP returns `FAILED` with `from_frame decode failed`.

For greenfield builds without a source frame, use the standard [Build Flow](#build-flow) above (`need: "protocol_match"`).

## Protocol Extend Flow

Use `protocol_extend_run` when the user wants to **add a new CSG 2016 message variant** (typically new DI under existing AFN 00–07). Extensions are written only to [`protocol_tool/protocols/csg_2016/variants/extensions/`](protocol_tool/protocols/csg_2016/variants/extensions/).

1. Call MCP with natural language:

```json
{"raw_input": "扩展 CSG 报文 AFN03 DI=E80304FF，查询延时时长"}
```

2. If `dir` or `add` is missing, MCP returns `need: "params"` with `missing_fields` — ask the user and resume:

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "dir": "downlink",
    "add": false,
    "description": "查询通信延时时长",
    "fields": [
      {"name": "timeout", "type": "uint16_le", "desc": "超时(秒)"}
    ]
  }
}
```

**结构体数组**（`count_ref` 必须引用同列表中靠前字段名）：

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "fields": [
      {"name": "node_count", "type": "uint8", "desc": "节点数量n"},
      {
        "name": "nodes",
        "type": "array",
        "count_ref": "node_count",
        "item_type": "struct",
        "item_name": "node",
        "desc": "节点地址+设备类型列表",
        "item_fields": [
          {"name": "address", "type": "bcd", "length": 6, "byte_order": "little", "desc": "地址"},
          {"name": "device_type", "type": "uint8", "desc": "设备类型"}
        ]
      }
    ]
  }
}
```

3. MCP returns `need: "confirm"` with `yaml_preview`. After user approval:

```json
{"run_id": "<run_id>", "user_input": {"confirm": true}}
```

4. On `SUCCEEDED`, MCP has already compiled the protocol and written **both** `compiled/protocol_map.json` and `compiled/protocol_map.yaml`, then verified `/route` resolves the new variant. Check `map_ok: true`, `map_files`, and `route_entries`. Re-run bootstrap only when SVG/cache cleanup is needed:

```bash
python3 scripts/bootstrap_protocol_cache.py
```

Limitations (v1):

- AFN must be 00–07 (existing routers). AFN 08+ returns `FAILED` with manual router hint.
- Duplicate DI+dir+add conflicts with existing variants are rejected.
- Do not edit `afn_payloads.yaml` directly; use this MCP flow instead.

## Decode Flow

For complete HEX decode requests, call MCP once with `raw_input`. MCP may detect the protocol and return `SUCCEEDED`.

## Rules

- Do not call CLI commands from the Agent for protocol work.
- Route selection must come from `protocol_map`.
- MCP owns state transitions, logging, route calls, build calls, decode verification, and retry counting.
- Agent owns natural-language matching and value construction from returned schemas.
