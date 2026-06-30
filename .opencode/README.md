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

两阶段：Phase 1 `collection_ready`（原始 DI/字段采集）→ Phase 2 逐条 `message_review`（用户 accept/skip/modify，可附 `modify_reason`）。详见 [`../AGENTS.md`](../AGENTS.md) Protocol Extend Flow。

Restart OpenCode after changing this file so the MCP registry is reloaded.

**协议扩展 C struct 限制与推荐写法**见 [`../AGENTS.md`](../AGENTS.md) Protocol Extend Flow →「C struct 表达能力」。

## Agent output

OpenCode loads `../AGENTS.md` as instructions. On protocol BUILD success, always paste the MCP `final_frame` hex verbatim — no `× N` / `[CS]` abbreviations.

## TestPlan + auto_rule（OpenCode 编排）

脚本自测默认 `vars.port: mock://auto`。`mock://auto` **只在显式 `auto_rule.add` 命中时回复**；无规则时 RX 为空，不会自动回确认帧。

### 最小示例（复制给 Agent）

见 [`../database/examples/mock_auto_ack.md`](../database/examples/mock_auto_ack.md) 与 [`../database/runs/mock_auto_ack.yaml`](../database/runs/mock_auto_ack.yaml)。

### 批量 / mock 规则（推荐写法）

大批量重复步骤与 mock 专用 setup **优先**：

| 能力 | 用途 | 示例 |
|------|------|------|
| **`parametrize`** | 数据驱动，加载时展开为线性 steps | [`add_slave_nodes_loop.yaml`](../database/runs/add_slave_nodes_loop.yaml) |
| **`include`** | 复用步骤片段（mock 规则、单批业务） | [`database/fragments/`](../database/fragments/) |
| **`when` 字符串** | 条件：`port == mock://auto` | include / if 的 `args.when` |

```yaml
# mock 规则（真机 plan 可省略整段 include）
- id: mock_rules
  action: include
  args:
    file: database/fragments/mock_add_slave_rules.yaml
    when: port == mock://auto

# 32 批添加从节点（compose 展开，无运行时 loop scope）
- id: add_slave_batches
  action: parametrize
  args:
    over: ${batches}
    as: batch
  steps:
    - action: include
      args:
        file: database/fragments/add_slave_batch_steps.yaml
```

仍支持 `loop` / `if`（见 [`loop_batch_demo.yaml`](../database/runs/loop_batch_demo.yaml)），新 plan 优先 parametrize + include。

### auto_rule 铁律

| 项 | 要求 |
|----|------|
| match | build 下行帧 DI 的 hex 子串（无空格），不用 `68.*16` |
| match 组合 | `match.all: [...]`（且）或 `match.any: [...]`（或） |
| then | dict 格式：`{command: /send, args: {hex: ...}}` 或 `{command: build, args: {...}}` |
| send → wait-frame | `send` 的 `timeout: 0` |
| setup / teardown | mock 规则放 `include` 片段；teardown 对应 `include` + remove |
| 动态上行 | `command: build` + `$request.user_data.*` + `$generated.slave_addrs` |

### 动态 build 示例（查询从节点信息）

见 [`database/fragments/mock_add_slave_rules.yaml`](../database/fragments/mock_add_slave_rules.yaml) 中 `register_rule_query_slave_info`；完整流程见 [`add_slave_nodes_loop.md`](../database/examples/add_slave_nodes_loop.md)。

### 双端 virtual 总线

`virtual://name` **不经过 auto_rule**；STA 需显式 `send` 响应。见 [`../database/examples/vendor_code_query.md`](../database/examples/vendor_code_query.md)。

### MCP 工作流

```text
protocol_task_run（每条报文）
  → 编写 TestPlan（database/templates/test_plan_mock_auto.yaml）
  → test.validate → test.dry_run
  → exec_test.run（真实串口 + execution_report）
```

编排校验用 **wireforge-test**；真实执行与业务报告用 **wireforge-exec-test**（`test.run` 仅 mock 快速自检）。

主文档：[`../database/examples/TEST_PLAN_AGENT.md`](../database/examples/TEST_PLAN_AGENT.md)
