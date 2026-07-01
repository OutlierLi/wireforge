# DLT645 扩展报文示例 — protocol_extend_run

对应 C 结构体：[`tests/fixtures/c_struct/dlt645_custom_energy.h`](../../tests/fixtures/c_struct/dlt645_custom_energy.h)

---

## 任务类型识别

`protocol_extend_run` 会按以下优先级识别 **CSG / DLT645**：

| 信号 | 判定 |
|------|------|
| `user_input.protocol` | `dlt645` / `csg` |
| `user_input.func` | DLT645 |
| `user_input.afn` | CSG |
| `di` 以 `E8` 开头 | CSG |
| 其他 8 位 DI | DLT645 |
| 文本含 `645` / `DLT645` / `func` | DLT645 |
| 文本含 `AFN` / `CSG` | CSG |

---

## MCP 调用示例（645 读数据应答）

```json
{
  "raw_input": "扩展 DLT645 读数据应答 DI 00099999",
  "user_input": {
    "protocol": "dlt645",
    "func": "0x11",
    "di": "00099999",
    "description": "自定义扩展电能量",
    "c_struct_path": "tests/fixtures/c_struct/dlt645_custom_energy.h"
  }
}
```

生成路径：`protocol_tool/protocols/dlt645_2007/variants/extensions/11_00099999.yaml`

### 其他 FUNC

| FUNC | router | selector | 默认 dir | 说明 |
|------|--------|----------|----------|------|
| 0x11 | `read_data_response_di` | `di` | uplink | 读数据应答载荷 |
| 0x14 | `write_data_request_di` | `di` | downlink | 写数据请求载荷 |
| 0x16 | `freeze_request_di` | `freeze_type` | downlink | 冻结命令载荷 |
| 0x1B | `clear_event_request_di` | `event_type` | downlink | 事件清零扩展载荷 |
| 其他 | `template_only` | — | 见注册表 | 需先在 protocol.yaml 添加 variant_router |

写数据扩展示例：

```json
{
  "raw_input": "扩展 DLT645 写数据 DI 00099999",
  "user_input": {
    "protocol": "dlt645",
    "func": "0x14",
    "di": "00099999",
    "description": "自定义写数据载荷",
    "c_struct_path": "tests/fixtures/c_struct/dlt645_custom_energy.h"
  }
}
```

冻结扩展示例（`di` 即 `freeze_type`）：

```json
{
  "user_input": {
    "protocol": "dlt645",
    "func": "0x16",
    "di": "00099999",
    "description": "自定义冻结类型",
    "c_struct": "typedef struct __attribute__((packed)) { bcd_datetime_t t; } payload_t;"
  }
}
```

---

## C 结构体头注释

```c
/* @wireforge func=11 di=00099999 dir=uplink desc="自定义扩展电能量" */
typedef struct __attribute__((packed)) {
    uint8_t rate_index; /* @desc 费率序号 */
    uint32_t energy_raw; /* @desc 电能量原始值 */
} custom_energy_t;
```

---

## 与 CSG 的差异

| 项 | CSG | DLT645 |
|----|-----|--------|
| 路由键 | `afn` + `di` + `dir` + `add` | `func` + `di`（0x16/0x1B 时 `di` 为 selector 值） |
| 扩展 router | `afnXX_di_router` | 见 `protocol_extend/dlt645_funcs.py` 注册表 |
| DI 格式 | `E8030306` | `00010000` |
| 默认方向 | 需指定 `dir` | 按 FUNC 自动（0x11→uplink，0x14/0x16→downlink） |

完成后运行 `python3 scripts/bootstrap_protocol_cache.py` 刷新 protocol map。
