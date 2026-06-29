# vendor_code_query — 自然语言描述 → TestPlan 示例

本示例展示如何用**自然语言**向 OpenCode 描述一条 CSG 厂商代码查询测试，Agent 编排为 TestPlan 后通过 **wireforge-test MCP** 执行（内联 `plan` 或落盘 YAML 均可）。

对应 TestPlan 文件：[`../runs/vendor_code_query.yaml`](../runs/vendor_code_query.yaml)

---

## 对 OpenCode 怎么说（复制即用）

```text
测试名：vendor_code_query

Setup
- 连接 cco → virtual://lab
- 连接 sta → virtual://lab
- 波特率 9600

Steps
1. CCO 侧 build CSG 下行读厂商代码（afn=0x03, di=E8000301, dir=downlink），save 为 query
2. STA 侧 build 对应上行响应（vendor_code=AB, chip_code=CD），save 为 resp
3. CCO send query
4. STA send resp（写到总线，CCO 可读）
5. CCO wait-frame：proto=csg，timeout 5s，expect afn=03 di=E8000301 dir=uplink
6. assert 收到的 frame_hex 等于 resp
7. decode 收到的帧，assert protocol=csg_2016

Teardown
- 断开 cco、sta

Options
- timeout_ms: 60000

请用 wireforge-test MCP：先 test.schema / test.validate / test.dry_run，再 test.run。
优先内联 plan 传递；若需持久化可参考 database/runs/vendor_code_query.yaml。
```

---

## 测试意图（一句话）

CCO 在 virtual 总线上发送 CSG 读厂商代码请求，STA 回复上行响应，CCO 应在 5 秒内收到并可正确 decode。

---

## 环境说明

| 角色 | 连接名 | 端口 | 说明 |
|------|--------|------|------|
| CCO（主站） | `cco` | `virtual://lab` | 发查询、监听响应 |
| STA（从站） | `sta` | `virtual://lab` | 发响应到同一 virtual 总线 |

virtual 总线规则：同一 `virtual://name` 下，一端写入的数据会进入其他端的读缓冲区；**本端写入不会回显**。

**注意**：`auto_rule` 仅在 `mock://auto` 生效；virtual 双端测试由 STA 显式 `send` 响应，不用 auto_rule。

---

## 步骤与期望

| 序号 | 步骤 | 期望 |
|------|------|------|
| 1 | CCO build 下行查询帧 | save_as `query` |
| 2 | STA build 上行响应帧 | save_as `resp`（vendor AB, chip CD） |
| 3 | CCO send `${query.frame_hex}` | 帧发出 |
| 4 | STA send `${resp.frame_hex}` | 响应进入总线，CCO 可读 |
| 5 | CCO wait-frame（5s） | 匹配 afn=03, di=E8000301, dir=uplink → `waited` |
| 6 | assert | `waited.frame_hex` == `resp.frame_hex` |
| 7 | decode + assert | `decoded.protocol` == `csg_2016` |
| — | teardown | 断开 cco、sta |

---

## Agent 编排后的 TestPlan 结构

```yaml
version: 1
name: vendor_code_query
timeout_ms: 60000

setup:
  - serial.connect cco → virtual://lab
  - serial.connect sta → virtual://lab

steps:
  - build (downlink query)  → save_as: query
  - build (uplink resp)     → save_as: resp
  - send cco / send sta
  - wait-frame cco          → save_as: waited
  - assert frame_hex
  - decode                  → save_as: decoded
  - assert protocol

teardown:
  - serial.disconnect cco
  - serial.disconnect sta
```

完整 YAML 见 [`../runs/vendor_code_query.yaml`](../runs/vendor_code_query.yaml)。

---

## 执行方式

### MCP（推荐）

```json
// test.run
{
  "file": "database/runs/vendor_code_query.yaml",
  "options": { "timeout_ms": 60000 }
}
```

或 Agent 生成 inline `plan` 对象，无需写文件。

### CLI

```bash
/run --file=database/runs/vendor_code_query.yaml --timeout=60000
```

---

## MCP 工作流

```text
自然语言描述
    → test.schema（可选，了解 action）
    → test.validate(plan)
    → test.dry_run(plan)
    → test.run(plan, options)
    → 失败时 test.read_report(report_dir, step_id)
```

报告目录默认：`log/run_reports/vendor_code_query_<timestamp>/`
