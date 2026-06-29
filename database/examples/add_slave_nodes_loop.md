# add_slave_nodes_loop — parametrize + include + mock 动态 build

对应 TestPlan：[`../runs/add_slave_nodes_loop.yaml`](../runs/add_slave_nodes_loop.yaml)

步骤片段：[`../fragments/`](../fragments/)（mock 规则、单批添加、单批查询）

---

## 测试意图

批量添加 1024 个从节点（32×32），验证档案初始化、添加从节点、查询数量、查询从节点信息等流程；`mock://auto` 下通过 `include` 引入多条 `auto_rule`，其中**查询从节点信息**使用 `command: build` 动态构帧。

---

## 对 OpenCode / Agent 怎么说

```text
测试名：add_slave_nodes_loop

编排风格（推荐）
- 重复步骤用 parametrize + include 片段，不用嵌套 loop
- mock 专用 setup/teardown 用 include + when: port == mock://auto
- 片段目录：database/fragments/

Setup
- serial.connect cco → mock://auto
- build 确认帧 → ack_frame；build 查询数量上行 → count_resp_frame
- include database/fragments/mock_add_slave_rules.yaml（when port == mock://auto）
  内含四条 auto_rule（初始化确认、添加确认、查询数量、查询从节点信息动态 build）

Steps
- 档案初始化 → send → wait 确认 → assert
- parametrize over batches（32 批）→ include add_slave_batch_steps.yaml
- 查询从节点数量 → assert slave_total=1024
- parametrize count:32 index_as query_idx → include query_slave_info_batch_steps.yaml

Teardown
- include mock_add_slave_rules_teardown.yaml（when mock）
- disconnect

编排前对每条报文走 protocol_task_run；test.validate → test.dry_run → exec_test.run。
```

---

## 结构说明

| 部分 | 写法 |
|------|------|
| mock 规则 | `include` → `mock_add_slave_rules.yaml` |
| 32 批添加 | `parametrize` + `include` → `add_slave_batch_steps.yaml` |
| 32 次查询 | `parametrize count:32` + `include` → `query_slave_info_batch_steps.yaml` |
| 真机 | 去掉 mock include；`exec_test.run` 传 `vars.port=/dev/ttyUSB0` |

加载 plan 时 `parametrize` / `include` 会 **compose 展开**为线性 steps（如 `add_slave_batches_0.build_add_slave_batch`），报告与 timeline 无 `[n]` loop 前缀。

---

## auto_rule 要点

| 规则 | match | then |
|------|-------|------|
| 档案初始化 | `020102E8` | send 确认帧 |
| 添加从节点 | `020402E8`（E8020402） | send 确认帧 |
| 查询数量 | `050300E8` | send 预 build 的上行 |
| 查询从节点信息 | `all: [060303E8, 0040]` | build + `$request` / `$generated.slave_addrs` |

动态 build 片段（在 fragment 内）：

```yaml
then:
  - command: build
    args:
      proto: csg
      afn: '0x03'
      di: E8040306
      dir: uplink
      slave_total: 1024
      response_slave_count: $request.user_data.slave_count
      slave_addrs: $generated.slave_addrs
```

---

## 执行

```json
{
  "file": "database/runs/add_slave_nodes_loop.yaml",
  "options": {
    "timeout_ms": 600000,
    "vars": {"port": "mock://auto"}
  }
}
```

真机将 `port` 改为 `/dev/ttyUSB0` 或 `COM3`，并确保 plan 中无 mock include（或 `when` 不匹配）。
