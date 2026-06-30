# WireForge Agent Rules

Use the MCP tool `protocol_task_run` for natural-language protocol build/decode/send tasks.

Use the MCP tool `protocol_extend_run` to add CSG 2016 variant extensions via **Agent-authored C structs** into `variants/extensions/` (C struct → YAML pipeline + stage logs under `log/protocol_extend_runs/`). Start with:

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
- `auto_rule.match` 用 build 下行帧的 DI hex 片段，不用宽泛 regex；可用 `match.all` / `match.any` 组合多分支
- `mock://auto` 无规则命中时不回复，必须显式 `auto_rule.add`；动态上行可用 `then: command: build` + `$request.*` / `$generated.slave_addrs`
- 重复步骤优先 `parametrize`（compose 展开为线性 steps）或 `include` 片段；仍可用 `loop` / `if`（见 TEST_PLAN_AGENT.md）
- mock 专用 setup 用 `include` + `when: port == mock://auto`，或拆分为独立 plan 文件
- 数组/结构体 vars 用 `${batch.addrs.0}`、`${device.port}` 访问
- 算术用 `expr` action 或 `${query_idx * 32}`；`loop`/`parametrize count` 可设 `index_as`
- 模版/示例：[`database/templates/test_plan_mock_auto.yaml`](database/templates/test_plan_mock_auto.yaml)、[`database/runs/add_slave_nodes_loop.yaml`](database/runs/add_slave_nodes_loop.yaml)（parametrize+include）、[`database/runs/loop_batch_demo.yaml`](database/runs/loop_batch_demo.yaml)（loop）

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

CSG 2016 **所有报文 payload** 均通过 **C 结构体 → YAML** 构造：

| 范围 | C struct 位置 | 生成 YAML |
|------|---------------|-----------|
| 内置报文（afn_payloads 原 DI 字段） | [`protocol_tool/protocols/csg_2016/c_struct/payloads/`](protocol_tool/protocols/csg_2016/c_struct/payloads/) + [`manifest.yaml`](protocol_tool/protocols/csg_2016/c_struct/manifest.yaml) | [`variants/payloads/`](protocol_tool/protocols/csg_2016/variants/payloads/)（`generate_csg_variants_from_c_struct.py`） |
| Agent 新增扩展 | MCP 传入 `c_struct_path` 或 inline | [`variants/extensions/`](protocol_tool/protocols/csg_2016/variants/extensions/)（`protocol_extend_run`） |

[`afn_payloads.yaml`](protocol_tool/protocols/csg_2016/variants/afn_payloads.yaml) 仅保留 **AFN 路由分组** 与 **空 payload 占位**；具体字段不在此文件手改。

**C 结构体中间层**（Agent 读协议 → 写 C struct → 代码生成 YAML）：

1. Agent **直接阅读**协议文档（DOCX / 导出 markdown / 规约原文）
2. 按 DI **payload**（不含 afn/seq/di/address_area）编写或修改 `c_struct/payloads/*.h`
3. 内置报文：更新 `c_struct/manifest.yaml` 后运行 `python3 scripts/generate_csg_variants_from_c_struct.py`（或 `bootstrap_protocol_cache.py`）
4. 新增 DI：调用 `protocol_extend_run`，传 `afn`、`di` 及 `c_struct` 或 `c_struct_path`
5. 审阅 `log/protocol_extend_runs/<run_id>/` 或 diff `variants/payloads/` / `variants/extensions/`

### C 结构体 DSL 要点

文件头元数据（可选，可替代 user_input 同名字段）：

```c
/* @wireforge afn=03 di=E8039999 dir=downlink desc="查询从节点信息" pair=true */
typedef struct __attribute__((packed)) {
    uint16_t start_slave_index; /* @desc 起始从节点序号 */
    uint8_t device_type;        /* @desc 设备类型 @enum 0x00:单相表 0x01:三相表 */
    node_address_t addr;        /* @domain node_address */
    uint8_t slave_count;        /* @desc 数量 */
    node_address_t addrs[];     /* @count_ref slave_count @item_name slave_addr */
} payload_t;
```

字段注解：`@desc` `@enum` `@domain` `@alias` `@unit` `@count_ref` `@length_ref` `@item_name` `@hex` `@default`

类型映射：`uint8_t`→`uint8`，`uint16_t`→`uint16_le`，`char[N]`→`ascii`，`uint8_t[N]`→`bytes`，嵌套 `struct{}`→`struct`，`T[]`+`@count_ref`→`array`，`struct{} name[]`+`@count_ref`→`array`（`item_type: struct`）。

### C struct 表达能力

**推荐写法：**

| 场景 | C struct 写法 |
|------|----------------|
| 纯地址列表 | `node_address_t addrs[]; /* @count_ref n @item_name addr */` |
| 复合元素列表 | `struct { ... } items[]; /* @count_ref n @item_name item */` |
| 6 字节时钟 ssmmhhDDMMYY | `bcd_datetime_t t; /* @domain bcd_datetime */` |
| 嵌套单字节 BCD | `uint8_t second[1]; /* @alias bcd */` → YAML `type: bcd, length: 1` |
| 定长 BCD 块 | `uint8_t longitude[4]; /* @alias bcd */` → YAML `type: bcd, length: 4` |
| 空 payload 查询 | MCP 传 `"empty_payload": true` |

**不支持（须改 parser 或暂用手写 `variants/extensions/*.yaml`）：**

- 定长 `struct { ... } items[N]`（N 为常数）

**兜底：** 若 `protocol_extend_run` 报 `unsupported field syntax` 且含 `struct { ... } xxx[]`，检查是否缺少 `@count_ref`；仍失败时可手写 `variants/extensions/{AFN}_{DI}.yaml` 后运行 bootstrap。

### 调用示例

```json
{
  "raw_input": "扩展 CSG 报文 AFN03 查询从节点信息",
  "user_input": {
    "afn": "03",
    "di": "E8039999",
    "dir": "downlink",
    "description": "查询从节点信息",
    "pair": true,
    "c_struct_path": "tests/fixtures/c_struct/query_slave_info_req.h",
    "resp_c_struct_path": "tests/fixtures/c_struct/query_slave_info_resp.h"
  }
}
```

### 限制

- 必须提供 `c_struct` 或 `c_struct_path`（及 `afn`、`di`）；空 payload 可用 `empty_payload: true`；成对报文另需 `resp_c_struct*` 或 `resp_empty_payload`
- 默认 `add: false`（无地址域）；AFN 08+ 可写 YAML（`template_only`），需在 `protocol.yaml` 添加 router 后 bootstrap
- C struct 仅描述 DI payload，不含 `user_data` 帧头

Re-run bootstrap when SVG/cache cleanup needed:

```bash
python3 scripts/bootstrap_protocol_cache.py
```

## Decode Flow

For complete HEX decode requests, call MCP once with `raw_input`. MCP may detect the protocol and return `SUCCEEDED`.

## Build 输出铁律（OpenCode / Agent）

`protocol_task_run` 返回 `state: "SUCCEEDED"` 时：

1. **必须原样输出** MCP 返回的 `final_frame`（完整 hex，空格分隔，含校验和与 `16` 结束符）。
2. **禁止缩写**：不得用 `× N`、`[CS]`、`...`、重复模式省略等替完整 hex。
3. **字段解析与报文分离**：解析表/说明可另写；完整报文单独放在代码块中，便于复制到串口工具。
4. 若用户问「完整报文/数据流」，优先贴 `final_frame`；可补充 `variant_id`、`decode_verified`、`checks`，但不得省略 hex 本体。

MCP 侧 `final_frame` 与 `decode.frame` 不做长度截断；数组类 decode 值（如 `nodes[]`）也不做条数省略。

## Rules

- Do not call CLI commands from the Agent for protocol work.
- Route selection must come from `protocol_map`.
- MCP owns state transitions, logging, route calls, build calls, decode verification, and retry counting.
- Agent owns natural-language matching and value construction from returned schemas.
