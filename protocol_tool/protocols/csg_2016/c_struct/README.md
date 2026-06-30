# CSG 2016 C 结构体 — 报文 payload 唯一来源

本目录是 **CSG 2016 所有 DI payload 字段** 的权威定义（不含帧头 `user_data` 中的 afn/seq/di/address_area）。

## 布局

```
c_struct/
  manifest.yaml      # variant id / router / match → c_struct 路径
  payloads/*.h       # WireForge C struct DSL（Agent 或迁移脚本维护）
```

生成 YAML（勿手改）：

```bash
PYTHONPATH=. python3 scripts/generate_csg_variants_from_c_struct.py
```

输出到 [`../variants/payloads/`](../variants/payloads/)，与 [`../afn_payloads.yaml`](../afn_payloads.yaml)（路由分组 + 空 payload 占位）一并由编译器加载。

## 工作流

1. **Agent / 开发者** 阅读规约，编辑 `payloads/*.h` 或新增条目到 `manifest.yaml`
2. 运行 `generate_csg_variants_from_c_struct.py`（或 `bootstrap_protocol_cache.py`，会自动生成）
3. `bootstrap_protocol_cache.py` 编译并刷新 `compiled/`

**新增扩展报文**仍用 `protocol_extend_run` MCP，写入 [`../variants/extensions/`](../variants/extensions/)；流程相同（C struct → YAML）。

## DSL

见 [`AGENTS.md`](../../../../AGENTS.md) Protocol Extend Flow。

### 常用注解

- `@desc` — 字段说明
- `@enum` — 取值表
- `@count_ref` / `@length_ref` — 变长数组 / 变长 hex
- `@item_name` — 数组元素命名前缀
- `@domain node_address` — 6 字节 BCD 地址
- `@domain bcd_datetime` — 6 字节 ssmmhhDDMMYY 时钟
- `@alias bcd` — 定长 BCD（`uint8_t x[N]` → `type: bcd, length: N`）
- `@default` — YAML default

### 模式示例

**标量柔性数组（纯地址列表）：**

```c
node_address_t slave_addrs[]; /* @count_ref response_slave_count @item_name slave_addr */
```

**嵌套 struct 柔性数组（复合元素）：**

```c
struct {
    node_address_t node_addr; /* @domain node_address */
    uint8_t device_type;
} node_infos[]; /* @count_ref node_count @item_name node_info */
```

**6 字节 CCO 时钟（优先 domain，勿写 6 个嵌套 BCD）：**

```c
bcd_datetime_t datetime; /* @domain bcd_datetime @desc CCO时钟 */
```
