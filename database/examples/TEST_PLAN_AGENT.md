# TestPlan Agent 编写指南

Agent 编排测试流程时的主参考文档。模版文件：[`../templates/test_plan_mock_auto.yaml`](../templates/test_plan_mock_auto.yaml)。

---

## 两个 MCP 的分工

| 阶段 | MCP | 工具 | 职责 |
|------|-----|------|------|
| **编排前** | wireforge（protocol） | `protocol_task_run` | 匹配报文、/route 取 `input_schema`、确认必填/默认/推导字段 |
| **编排后** | wireforge-test | `test.validate` … `test.run` | 校验/展开/执行 TestPlan YAML |

**禁止**跳过 protocol MCP 直接写 TestPlan 或猜测 build 字段名。

---

## Phase 0：编排前置（强制）

### 流程

1. 根据用户需求列出**依赖报文清单**（下行请求、上行响应、mock 规则用帧）
2. 对清单中每一条调用 `protocol_task_run`（见 [`AGENTS.md`](../../AGENTS.md) Build Flow）
3. 对照 `input_schema` / `required_fields` / `defaulted_fields` / `derived_fields`
4. 全部齐备后再复制模版、编写 YAML
5. `test.validate` → `test.dry_run` → `test.run`（每步对 `build` 做 route schema 校验；`dry_run` 通过表示字段名与 route 一致）

`test.dry_run` 失败时查看 `errors` / `build_checks` 中的 `unknown_fields`、`missing_required`、`input_schema`，对照 Phase 0 的 route 结果修正 YAML。

### 依赖清单示例

| 序号 | 角色 | 方向 | 描述 | route_params | required_fields | 来源 |
|------|------|------|------|--------------|-----------------|------|
| 1 | 被测 | downlink | 档案初始化 | afn=01 di=E8020102 | — | 用户 |
| 2 | mock | uplink | 确认帧 | afn=00 di=E8010001 | wait_time | auto_rule |

### 必须停止并询问用户的情况

| 情况 | Agent 行为 |
|------|------------|
| 无 candidate 匹配 | 回复：`未识别的报文，请补充协议地图描述。` |
| 多个 entry 同 leaf_id | 请用户澄清 dir/add |
| `required_fields` 未提供且无法推断 | 展示参数表，请用户补充 |
| 用户值与 schema 类型/长度冲突 | 说明冲突，请用户修改 |
| protocol_map 缺失 | 提示运行 `python3 scripts/bootstrap_protocol_cache.py` |

### MCP schema → TestPlan build

```yaml
- id: build_init_archive
  action: build
  args:
    proto: csg              # route_params.proto
    afn: "0x01"             # route_params.afn
    di: E8020102            # route_params.di
    dir: downlink           # route_params.dir
    # 其余字段名必须与 input_schema.name 一致
  save_as: init_frame
```

---

## Phase 1：脚本验证（mock://auto）

模版默认变量：

```yaml
vars:
  port: mock://auto    # 不传 options.vars.port 时使用
  conn: cco
  baudrate: 9600
  proto: csg
```

`mock://auto`：写入帧经 auto_rule 匹配后生成 RX，适合验证 TestPlan 逻辑，无需真机。

---

## Phase 2：真机执行

```json
{
  "file": "database/runs/my_test.yaml",
  "options": {
    "timeout_ms": 120000,
    "vars": {"port": "/dev/ttyUSB0"}
  }
}
```

Windows 示例：`"port": "COM3"`。未传 `port` 则保持 `mock://auto`。

---

## 命令速查

### build — 构造报文

```yaml
- id: build_query
  action: build
  args:
    proto: csg
    afn: "0x03"
    di: E8000301
    dir: downlink
  save_as: query
```

- 字段名/类型以 protocol MCP 的 `input_schema` 为准
- `save_as` 后可用 `${query.frame}`、`${query.frame_hex}`
- 禁止手拼 hex

### send — 发送

```yaml
- id: send_query
  action: send
  args:
    conn: ${conn}
    hex: ${query.frame_hex}
    timeout: 0          # 后接 wait-frame 时必须为 0
```

`timeout: 0` 表示只发不等；mock 回复留给 `wait-frame` 读取。

### wait-frame — 等待响应

```yaml
- id: wait_resp
  action: wait-frame
  args:
    conn: ${conn}
    proto: ${proto}
    timeout_ms: 5000
    expect:
      afn: "03"
      di: E8000301
      dir: uplink
  save_as: resp
```

assert 示例：`resp.matched: true` 或 `resp.decoded.user_data.slave_total: 1024`

### decode — 解码

```yaml
- id: decode_resp
  action: decode
  args:
    proto: csg
    hex: ${resp.frame_hex}
  save_as: decoded
```

优先用 `wait-frame` 的 `save_as.decoded.*` 做 assert；decode 步骤用于额外校验。

### assert — 断言

```yaml
- id: check
  action: assert
  args:
    expect:
      resp.matched: true
      resp.decoded.user_data.slave_total: 1024
```

### auto_rule.add — mock 自动回复

**不推荐**：`68.*16`、`68..00..E8` 等宽泛 regex。

**推荐**：

1. build 要被匹配的**下行帧**
2. 从 `${frame}` 去空格，取唯一 **DI hex 片段** 作为 `match`
3. `then` 用 dict 格式引用 pre-build 的上行帧

```yaml
- id: build_count_resp
  action: build
  args:
    proto: csg
    afn: "0x03"
    di: E8000305
    dir: uplink
    slave_total: 1024
  save_as: count_resp

- id: add_rule_count
  action: auto_rule.add
  args:
    id: rule_query_count
    match: "050300E8"
    source: serial:${conn}
    then:
      - command: /send
        args:
          hex: ${count_resp.frame}
```

DI 片段来源：查询数量下行 `E8000305` → 线上字节 `05 03 00 E8` → match `050300E8`。

**mock://auto 内置兜底**（[`wireforge_serial/transport.py`](../../wireforge_serial/transport.py)）：查询从节点信息（`060303E8`）按 `start_slave_index` 动态生成地址；其它未命中规则的下行为确认帧。优先写显式 auto_rule。

### serial.connect / disconnect

```yaml
setup:
  - action: serial.connect
    args:
      conn: ${conn}
      port: ${port}
      baudrate: ${baudrate}

teardown:
  - action: serial.disconnect
    args:
      conn: ${conn}
```

---

## 控制流与复合变量

### 结构体 / 数组 vars

```yaml
vars:
  batches:
    - start_index: 0
      addrs: ["01 00 00 00 00 00", "02 00 00 00 00 00"]
  device:
    port: mock://auto
```

路径示例：

- `${batches.0.start_index}`、`${batches[0].addrs.1}`
- `${device.port}`
- 整对象：`value: ${batches.0}`（保留 dict/list 类型，用于 `set_var`）

### loop — 遍历数组或计数

```yaml
- id: loop_batches
  action: loop
  args:
    over: ${batches}    # 或 vars 名 batches
    as: batch           # 当前元素，默认 item
    index_as: i         # 可选下标
  steps:
    - id: use_batch
      action: set_var
      args:
        name: idx
        value: ${batch.start_index}

- id: loop_n
  action: loop
  args:
    count: 32
    start: 0            # 可选，默认 0
    index_as: i
  steps:
    - action: set_var
      args: {name: n, value: ${i}}
```

重复步骤用 `loop`，避免复制粘贴上百个 step。

### if — 条件分支

```yaml
- id: only_on_mock
  action: if
  args:
    when:
      eq:
        port: mock://auto
  steps:
    - action: auto_rule.add
      ...
  else_steps:
    - action: sleep
      args: {ms: 100}
```

`when` 语法：

- `eq: {path: expected}` — 同 assert
- `not: {eq: {...}}` — 取反
- `all: [{eq:...}, {not:...}]` — 全部满足

### expr — 算术表达式

`count` 循环未写 `index_as` 时，自动注入 **`i`** 与 **`qi`**（均为当前轮次索引，从 `start` 起算）。`over` 循环未写时仅注入 **`i`**。显式 `index_as: xxx` 时只用 `xxx`。

```yaml
- id: loop_batches
  action: loop
  args:
    count: 33
    # 等价于 index_as: qi；子步骤可用 qi 或 i
  steps:
    - id: calc_start
      action: expr
      args:
        name: start_index
        expr: qi * 32

    - id: inline_expr
      action: set_var
      args:
        name: start_index
        value: ${qi * 32 + 1}
```

支持运算符：`+`、`-`、`*`、`//`、`%`；变量须为数值（或数字字符串）。

### loop 作用域

- 每轮迭代从外层 vars 重新开始，迭代间互不污染
- 循环结束后保留**最后一轮**写入的 vars（如 `save_as` / `set_var`）
- 外层 vars 不会被中间轮次修改

### dry_run loop 预览

当 `over` / `count` 在编译期可解析时，`test.dry_run` 在对应 loop step 上附加 `loop_preview`（最多展开 32 轮），便于 Agent 检查子步骤变量是否解析正确。

示例：[`../runs/loop_batch_demo.yaml`](../runs/loop_batch_demo.yaml)

---

## 协议信息从哪里查

| 目的 | 路径 |
|------|------|
| 协议注册表 | [`protocol_tool/protocols/registry.yaml`](../../protocol_tool/protocols/registry.yaml) |
| CSG AFN/DI/字段 | [`protocol_tool/protocols/csg_2016/variants/afn_payloads.yaml`](../../protocol_tool/protocols/csg_2016/variants/afn_payloads.yaml) |
| DLT645 变体 | [`protocol_tool/protocols/dlt645_2007/variants/`](../../protocol_tool/protocols/dlt645_2007/variants/) |
| 帧结构 | 各协议目录下 `frame.yaml` |
| **报文索引（首选）** | [`compiled/protocol_map.yaml`](../../compiled/protocol_map.yaml) |
| IR（build 路由） | [`compiled/csg_2016.ir.json`](../../compiled/csg_2016.ir.json) 等 |

运行 bootstrap 生成索引：

```bash
python3 scripts/bootstrap_protocol_cache.py
```

---

## 示例索引

| 示例 | 文件 | 场景 |
|------|------|------|
| 最小 mock | [`mock_auto_ack.md`](mock_auto_ack.md) | 单连接 mock://auto + auto_rule |
| loop/if 演示 | [`../runs/loop_batch_demo.yaml`](../runs/loop_batch_demo.yaml) | 数组/结构体 vars + loop + if |
| 双端 virtual | [`vendor_code_query.md`](vendor_code_query.md) | CCO + STA 总线 |
| 动作覆盖 | [`../runs/all_actions.yaml`](../runs/all_actions.yaml) | 全部 action 类型 |

---

## test MCP 工作流

```text
Phase 0: protocol_task_run（每条报文确认 schema）
    ↓
编写 YAML（从模版复制）
    ↓
test.schema（build_field_types、workflow、模版与约定）
test.validate(plan) — 结构 + build/route schema
test.dry_run(plan, vars?) — 展开变量 + build schema（通过 ≈ 字段与 route 一致）
test.run(plan, options) — 默认同样 build check（options.skip_build_check 仅调试）
    ↓ 失败
test.read_report(report_dir, step_id)
```

报告默认目录：`log/run_reports/<run_id>/`
