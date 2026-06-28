# mock_auto_ack — 最小 mock://auto 示例

对应 TestPlan：[`../runs/mock_auto_ack.yaml`](../runs/mock_auto_ack.yaml)

---

## 测试意图

CCO 通过 `mock://auto` 发送 CSG 档案初始化下行帧，auto_rule 自动回复确认帧（AFN=00, DI=E8010001），`wait-frame` 应匹配成功。

---

## 编排前置（protocol MCP）

编写 YAML 前，Agent 应对依赖报文走 `protocol_task_run`：

| 序号 | 方向 | 描述 | route_params | 备注 |
|------|------|------|--------------|------|
| 1 | downlink | 档案初始化 | proto=csg afn=01 di=E8020102 dir=downlink | 无必填 payload 字段 |
| 2 | uplink | 确认帧 | proto=csg afn=00 di=E8010001 dir=uplink | wait_time 可用默认 0 |

缺匹配或缺必填参数时**停止编排**，向用户索要参数（见 AGENTS.md Build Flow）。

---

## 对 Agent 怎么说

```text
测试名：mock_auto_ack

Setup
- 连接 cco → mock://auto，9600
- build 确认帧 uplink（afn=0x00, di=E8010001）→ ack_frame
- auto_rule：匹配档案初始化 DI 片段 020102E8，回复 ack_frame

Steps
1. build 档案初始化 downlink（afn=0x01, di=E8020102）
2. send（timeout=0）
3. wait-frame expect afn=00 di=E8010001 dir=uplink
4. assert matched=true

Teardown
- 删除 auto_rule、断开串口

先用 test.validate / test.dry_run，再 test.run。
真机时将 options.vars.port 设为实际串口。
```

---

## auto_rule 匹配说明

档案初始化下行帧 build 后 hex 含 DI 字节序列 `020102E8`（来自 `E8020102`），用作 `match`，**不用** `68.*16` 等宽泛正则。

---

## 执行

```json
{
  "file": "database/runs/mock_auto_ack.yaml",
  "options": {"timeout_ms": 60000}
}
```

真机覆盖串口：

```json
{
  "file": "database/runs/mock_auto_ack.yaml",
  "options": {"vars": {"port": "/dev/ttyUSB0"}}
}
```
