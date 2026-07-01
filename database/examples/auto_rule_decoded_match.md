# auto_rule_decoded_match — 解析后语义匹配（mock://auto）

对应 TestPlan：[`../runs/auto_rule_decoded_match.yaml`](../runs/auto_rule_decoded_match.yaml)

---

## 测试意图

在 `mock://auto` 下验证 **decode 后按 DI/AFN/方向及 payload 字段** 匹配，而不是对原始 hex 做宽泛正则。

`mock://auto` 行为：`send` 下行帧 → 规则引擎 decode → 条件命中 → `then` 回复进入 RX。

---

## 三种写法

### 1. 顶层 `di`（推荐）

build 参数里的 DI 可直接写，无需记 decode 输出的 `E8 03 03 06` 格式：

```yaml
action: auto_rule.add
args:
  id: rule_di_only
  di: E8030306
  then:
    - command: /send
      args:
        hex: AA
```

等价于解析后匹配 `user_data.di`（自动归一化 hex）。

### 2. 多条路由条件 `match.all`

```yaml
match:
  all:
    - di: E8030306
      afn: '03'
      dir: downlink
```

`afn` 支持 `03` / `0x03` / `3` 归一化比较。

### 3. DI + 数据域短字段名

```yaml
match:
  di: E8030306
  dir: downlink
  slave_count: '32'
```

未带点号的字段名默认映射为 `user_data.<name>`；`dir` 为帧级字段。

仍可与 hex 片段混用（旧写法）：

```yaml
match:
  all:
    - '060303E8'
    - type: decoded
      fields:
        user_data.slave_count: '32'
```

---

## 编排前置

| 报文 | route_params |
|------|----------------|
| 查询从节点信息 downlink | proto=csg afn=03 di=E8030306 dir=downlink start_slave_index slave_count |

---

## 执行

```json
{
  "file": "database/runs/auto_rule_decoded_match.yaml",
  "options": {"timeout_ms": 120000}
}
```

MCP：`test.validate` → `test.dry_run` → `test.run`。

---

## 注意

- 仅 **`mock://auto`** 在 TestPlan 中自动触发规则；真机串口需设备侧应答或另行接入。
- decode 协议默认 **csg**；规则级 `--proto csg|dlt645`（或 YAML `proto:`）指定 decode 所用协议。
- DLT645 用 `--proto dlt645 --di 00010000 --func 0x11`；645 无 AFN，用 `func` 代替。
- 条件含 decoded/route 字段时会按规则 `proto` 自动 parse。
- 同 DI 多条规则时 **后添加的覆盖** 先添加的。
