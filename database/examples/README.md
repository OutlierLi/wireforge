# TestPlan 示例与 Agent 文档

## 模版

| 文件 | 说明 |
|------|------|
| [`../templates/test_plan_mock_auto.yaml`](../templates/test_plan_mock_auto.yaml) | 单连接 mock://auto 基础模版（复制后填写 steps） |

## Agent 主文档

| 文件 | 说明 |
|------|------|
| [`TEST_PLAN_AGENT.md`](TEST_PLAN_AGENT.md) | 编排规范、命令速查、protocol MCP 前置流程、协议路径 |

## 可运行示例

| 说明 | TestPlan | 文档 |
|------|----------|------|
| mock 确认帧（最小） | [`../runs/mock_auto_ack.yaml`](../runs/mock_auto_ack.yaml) | [`mock_auto_ack.md`](mock_auto_ack.md) |
| 批量添加从节点（parametrize+include） | [`../runs/add_slave_nodes_loop.yaml`](../runs/add_slave_nodes_loop.yaml) | [`add_slave_nodes_loop.md`](add_slave_nodes_loop.md) |
| 步骤片段（mock/单批） | [`../fragments/`](../fragments/) | [`add_slave_nodes_loop.md`](add_slave_nodes_loop.md) |
| loop/if 演示（旧写法，仍支持） | [`../runs/loop_batch_demo.yaml`](../runs/loop_batch_demo.yaml) | [`TEST_PLAN_AGENT.md`](TEST_PLAN_AGENT.md) |
| virtual 双端查询 | [`../runs/vendor_code_query.yaml`](../runs/vendor_code_query.yaml) | [`vendor_code_query.md`](vendor_code_query.md) |
| 全 action 覆盖 | [`../runs/all_actions.yaml`](../runs/all_actions.yaml) | — |

## auto_rule（mock://auto）

- **无兜底**：未命中规则时不回复，setup 须显式注册每条 mock 应答
- **match**：build 下行 DI hex 子串；可用 `match.all` / `match.any`
- **then**：dict 格式；静态用 `command: /send`，动态用 `command: build` + `$request.*`
- OpenCode 速查：[`.opencode/README.md`](../../.opencode/README.md)

## 协议源文件

- 注册表：[`protocol_tool/protocols/registry.yaml`](../../protocol_tool/protocols/registry.yaml)
- 编译索引：[`compiled/protocol_map.yaml`](../../compiled/protocol_map.yaml)（需 `python3 scripts/bootstrap_protocol_cache.py`）

## 串口变量约定

- 默认 `vars.port: mock://auto`（脚本自测）
- 真机：`test.run` 传 `options.vars.port`（如 `/dev/ttyUSB0`、`COM3`）
