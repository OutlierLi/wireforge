# WireForge 命令参考

> 自动生成于 2026-07-01 22:40:02 +0800；源文件 [`console/commands.json`](../../console/commands.json)。
> 重新生成：`python3 scripts/generate_commands_reference.py`

## 符号说明

| 写法 | 含义 |
|------|------|
| `<参数>` | **必填** |
| `〔参数〕` | **可选，建议指定** |
| `[参数]` | **可选** |

参数在用法行与下表中按 **必填 → 推荐 → 可选** 排序。

### 十六进制参数（`hex` / `from_frame` 等）

命令行文本支持以下写法（空格可有可无）：

- 连续 hex：`--hex=680C00400301010300E83016`
- 带空格 + 引号：`--hex "68 0C 00 40 03 01 01 03 00 E8 30 16"`
- 等号 + 引号：`--hex="68 0C 00 40 03 01 01 03 00 E8 30 16"`
- 无引号多 token：`--hex 68 0C 00 40 03 01 01 03 00 E8 30 16`

JSON/API 调用直接传字符串即可，例如 `{"hex": "68 0C ..."}`。

---

## /auto_rule

**功能**：mock://auto 自动应答规则引擎

### 子命令

#### `/auto_rule add`

**功能**：新增自动应答规则

**用法**：`/auto_rule add <id> <match> <then> [afn] [di] [dir] [field] [func] [name] [proto] [source]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID（唯一，后续 show/enable/delete/update/test 均用此标识）；示例 csg_query_vendor_ack、auto_reply_login |
| `match` | 必填 | str | 匹配条件：regex/JSON 片段，或用 field/di/afn/dir 指定解码字段条件；与 --field/--di/--afn/--dir 二选一或组合；不可省略；示例 010300E8、68.*16、{"all":["010300E8","0040"]} |
| `then` | 必填 | str | 匹配后执行的命令（Shell 命令行，与 /send /print 相同写法）；无需 JSON；--then /print --text=ok 即可（shell 会自动合并 --text）；输入 / 可联想嵌套命令；示例 /print --text=success、/send --hex "68 0D 00 80 00 01 01 00 01 E8 00 6B 16"、/log --message matched |
| `afn` | 可选 | hex | 按 AFN 精确匹配（decoded 条件） |
| `di` | 可选 | str | 按 DI 精确匹配（decoded 条件） |
| `dir` | 可选 | choice | 按方向匹配（decoded 条件）；示例 downlink、uplink |
| `field` | 可选 | str | 解码字段条件 field=path=value，可替代或补充 match |
| `func` | 可选 | hex | 按功能码匹配（DLT645 decoded 条件）；示例 0x11、11 |
| `name` | 可选 | str | 规则显示名称（可选，list 时展示；不影响匹配逻辑） |
| `proto` | 可选 | choice | decode 匹配所用协议（默认 csg）；decoded/di/afn/func 条件依赖此协议解析帧；645 用 --proto dlt645 --di --func；示例 csg、dlt645 |
| `source` | 可选 | str | 触发源 serial:default |

#### `/auto_rule list`

**功能**：列出所有规则

**用法**：`/auto_rule list`

#### `/auto_rule show`

**功能**：查看规则详情

**用法**：`/auto_rule show <id>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID |

#### `/auto_rule enable`

**功能**：启用规则

**用法**：`/auto_rule enable <id>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID |

#### `/auto_rule disable`

**功能**：禁用规则

**用法**：`/auto_rule disable <id>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID |

#### `/auto_rule delete`

**功能**：删除规则

**用法**：`/auto_rule delete <id>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID |

#### `/auto_rule test`

**功能**：用 hex 报文 dry-run 测试规则

**用法**：`/auto_rule test <id> <hex>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 必填 | str | 规则ID |
| `hex` | 必填 | str | 测试用十六进制报文 |

#### `/auto_rule load`

**功能**：从 YAML 加载规则

**用法**：`/auto_rule load <file>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `file` | 必填 | str | YAML规则文件路径 |

#### `/auto_rule history`

**功能**：查看规则匹配历史

**用法**：`/auto_rule history [id]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `id` | 可选 | str | 规则ID（可选过滤） |

---

## /build

**功能**：根据协议目标构造报文帧

### 子命令

#### `/build build`

**功能**：根据 proto/afn/di 等构造报文

**用法**：`/build build <proto> [afn] [di] [dir] [func] [set]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `proto` | 必填 | choice | 协议类型；示例 dlt645、csg |
| `afn` | 可选 | hex | 应用功能码 (CSG)；示例 0x00、0x03 |
| `di` | 可选 | str | 数据标识DI；示例 00010000、E8020701 |
| `dir` | 可选 | choice | 传输方向；默认 `downlink`；示例 downlink、uplink |
| `func` | 可选 | hex | 功能码 (DLT645)；示例 0x11、0x13 |
| `set` | 可选 | str | 设置/覆盖字段值；示例 di=00020000、freeze_year=26 |

#### `/build from-frame`

**功能**：从已有 hex 报文修改字段后重建

**用法**：`/build from-frame <from_frame> [proto] [set]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `from_frame` | 必填 | str | 从已有 hex 报文解码后修改字段再重建；示例 FE FE 68 ... 16 |
| `proto` | 可选 | choice | 协议类型（省略则自动检测）；示例 dlt645、csg |
| `set` | 可选 | str | 设置/覆盖字段值；示例 di=00020000、freeze_year=26 |

#### `/build resolve`

**功能**：仅解析目标，返回 input_schema

**用法**：`/build resolve <proto> [afn] [di] [dir] [func]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `proto` | 必填 | choice | 协议类型；示例 dlt645、csg |
| `afn` | 可选 | hex | 应用功能码 (CSG)；示例 0x00、0x03 |
| `di` | 可选 | str | 数据标识DI；示例 00010000、E8020701 |
| `dir` | 可选 | choice | 传输方向；默认 `downlink`；示例 downlink、uplink |
| `func` | 可选 | hex | 功能码 (DLT645)；示例 0x11、0x13 |

---

## /decode

**功能**：将十六进制报文解码为结构化字段与路由路径

### 子命令

#### `/decode decode`

**功能**：解码十六进制报文

**用法**：`/decode decode <proto> <hex>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `proto` | 必填 | choice | 协议类型；示例 dlt645、csg |
| `hex` | 必填 | str | 十六进制报文字节流；示例 FE FE 68 ... 16、68 0C 00 40 03 01 01 03 00 E8 30 16 |

---

## /delay

**功能**：延时等待，支持毫秒或 s 后缀

### 子命令

#### `/delay wait`

**功能**：延时等待

**用法**：`/delay wait <value>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `value` | 必填 | str | 时长，默认 ms，支持 s 后缀；示例 100、500ms、2s、1.5s |

---

## /find

**功能**：Search protocol messages by keyword, DI, AFN, func, or direction. /find 初始化档案 or /find E8020102

### 子命令

#### `/find search`

**功能**：Search protocol messages by keyword, DI, AFN, func, or direction. /find 初始化档案 or /find E8020102

**用法**：`/find search [afn] [di] [dir] [filter] [func] [meaning] [proto]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `afn` | 可选 | hex | 按 AFN 精确匹配（CSG）；示例 0x01、0x06 |
| `di` | 可选 | str | 按 DI 精确匹配；示例 E8020102、00010000 |
| `dir` | 可选 | choice | 按传输方向过滤；示例 downlink、uplink |
| `filter` | 可选 | str | 额外 AND 过滤条件，可多次使用；示例 档案、uplink、心跳 |
| `func` | 可选 | hex | 按功能码精确匹配（DLT645）；示例 0x11、0x13 |
| `meaning` | 可选 | str | 全文模糊搜索关键词；示例 初始化、查询 |
| `proto` | 可选 | choice | 协议类型（不指定则搜索全部）；示例 dlt645、csg |

---

## /help

**功能**：查看命令与子命令帮助

### 子命令

#### `/help show`

**功能**：显示命令帮助

**用法**：`/help show [target]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `target` | 可选 | str | Command name, e.g. /serial；示例 /serial、/serial open |

---

## /print

**功能**：打印文本，支持 ${变量} 插值

### 子命令

#### `/print text`

**功能**：打印文本

**用法**：`/print text <text> [raw]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `text` | 必填 | str | 文本内容，支持 ${name} 变量引用和 ${object.field} 路径访问；示例 当前协议：${protocol}、${frame}、AFN=${afn} |
| `raw` | 可选 | bool | 原样输出，不解析变量引用 |

---

## /request

**功能**：发送报文并等待匹配响应（自动化测试原语）

### 子命令

#### `/request send`

**功能**：发送并等待匹配响应

**用法**：`/request send <send> 〔to〕 [proto] [timeout] [wait.afn] [wait.di] [wait.dir]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `send` | 必填 | str | Hex frame to send；示例 68 0C 00 40 03 01 01 03 00 E8 30 16 |
| `to` | 推荐 | str | Serial connection target；示例 default、cco |
| `proto` | 可选 | choice | Protocol for decode (auto-detect if omitted)；示例 csg、dlt645 |
| `timeout` | 可选 | int | Max wait time in ms；默认 `5000`；示例 3000、5000 |
| `wait.afn` | 可选 | str | Expected AFN in response |
| `wait.di` | 可选 | str | Expected DI in response |
| `wait.dir` | 可选 | choice | Expected direction in response；示例 uplink、downlink |

---

## /route

**功能**：解析协议路由路径与 input_schema（/build 前置步骤）

### 子命令

#### `/route resolve`

**功能**：解析路由与 input_schema

**用法**：`/route resolve <proto> [afn] [di] [dir] [func]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `proto` | 必填 | choice | 协议类型；示例 dlt645、csg |
| `afn` | 可选 | hex | 应用功能码 (CSG)；示例 0x00、0x06 |
| `di` | 可选 | str | 数据标识DI；示例 00010000、E8010601 |
| `dir` | 可选 | choice | 传输方向；默认 `downlink`；示例 downlink、uplink |
| `func` | 可选 | hex | 功能码 (DLT645)；示例 0x11、0x13 |

---

## /run

**功能**：执行 YAML TestPlan 编排测试

### 子命令

#### `/run execute`

**功能**：执行 TestPlan

**用法**：`/run execute <file> [dry-run] [json] [report] [timeout] [var]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `file` | 必填 | str | TestPlan YAML file；示例 tests/sta_join.yaml |
| `dry-run` | 可选 | bool | Resolve and report steps without executing serial/protocol commands |
| `json` | 可选 | bool | Reserved for structured clients; command response is always structured |
| `report` | 可选 | str | Report output directory；示例 reports/sta_join_001 |
| `timeout` | 可选 | int | Override total run timeout in ms；示例 120000 |
| `var` | 可选 | str | Override plan variable; may be repeated；示例 cco=COM9、sta=COM10 |

---

## /serial

**功能**：串口连接管理：连接、发送、关闭、列举端口等

### 子命令

#### `/serial connect`

**功能**：首次连接，必须指定 port

**用法**：`/serial connect <port> 〔name〕 [baudrate] [bytesize] [display] [parity]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `port` | 必填 | str | 串口号；默认 `mock://loop`；mock=内存回环, virtual=跨进程总线, 其他=物理串口；示例 mock://loop、virtual://demo、/dev/ttyUSB0、COM3 |
| `name` | 推荐 | str | 连接名称（注册到串口池）；默认 `default`；后续 send/wait-frame 等用 `--to` 选择；示例 default、cco、sta1 |
| `baudrate` | 可选 | int | 波特率；默认 `9600`；示例 9600、115200 |
| `bytesize` | 可选 | int | 数据位；默认 `8`；示例 8 |
| `display` | 可选 | choice | RX 终端显示格式；默认 `hex`；示例 hex、ascii |
| `parity` | 可选 | choice | 校验位；默认 `N`；示例 N、E、O |

#### `/serial open`

**功能**：用上次参数重新打开连接

**用法**：`/serial open 〔name〕`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 连接名称；默认 `default`；示例 default、cco |

#### `/serial close`

**功能**：关闭指定连接

**用法**：`/serial close 〔name〕`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 连接名称；示例 default、cco |

#### `/serial disconnect`

**功能**：close 的别名

**用法**：`/serial disconnect 〔name〕`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 连接名称；示例 default、cco |

#### `/serial send`

**功能**：仅发送十六进制帧

**用法**：`/serial send <hex> 〔to〕`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `hex` | 必填 | str | 发送数据(十六进制)；示例 68 0C 00 40 03 01 01 03 00 E8 30 16 |
| `to` | 推荐 | str | 选择已注册的连接名称；仅一个已连接串口时可省略；多连接时必须指定；示例 default、cco |

#### `/serial set`

**功能**：修改串口参数（下次 open 生效）

**用法**：`/serial set 〔name〕 [baudrate] [bytesize] [display] [parity]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 连接名称；示例 default、cco |
| `baudrate` | 可选 | int | 波特率；示例 9600、115200 |
| `bytesize` | 可选 | int | 数据位；示例 8 |
| `display` | 可选 | choice | RX 终端显示格式；示例 hex、ascii |
| `parity` | 可选 | choice | 校验位；示例 N、E、O |

#### `/serial ports`

**功能**：列出可用串口与当前连接状态

**用法**：`/serial ports`

#### `/serial list`

**功能**：ports 的别名

**用法**：`/serial list`

---

## /split

**功能**：在新终端窗口/标签/分栏中继承当前会话状态

### 子命令

#### `/split open`

**功能**：打开新终端窗口/标签

**用法**：`/split open [dry-run] [mode]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `dry-run` | 可选 | bool | 仅打印启动命令，不实际执行 |
| `mode` | 可选 | choice | 启动模式；默认 `tab`；示例 split、tab、window |

---

## /time

**功能**：Toggle timestamp prefix on serial TX/RX terminal display. /time on | /time off

### 子命令

#### `/time on`

**功能**：Enable timestamp on serial display output

**用法**：`/time on`

#### `/time off`

**功能**：Disable timestamp on serial display output

**用法**：`/time off`

---

## /upg

**功能**：CSG AFN=07 固件文件传输/升级

### 子命令

#### `/upg transfer`

**功能**：固件文件传输

**用法**：`/upg transfer <file> [ack-timeout] [ack-wait] [build-only] [clear] [dest] [file-id] [file-type] [final-ack-timeout] [finish] [finish-timeout] [interval] [no-cache] [no-resume] [proto] [resume] [retries] [segment-size] [seq] [timeout] [timeout-min] [to]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `file` | 必填 | str | Firmware file path (quotes and database/bin relative paths supported)；示例 database/bin/firmware_v2.bin、"/path/with spaces/fw.bin" |
| `ack-timeout` | 可选 | str | Per-segment ACK timeout (e.g. 5s, 500ms); alias: timeout；默认 `5s`；示例 5s、10s |
| `ack-wait` | 可选 | str | ACK wait_time handling: ignore or respect；默认 `ignore`；示例 ignore、respect |
| `build-only` | 可选 | bool | Only build/validate cache, do not transfer |
| `clear` | 可选 | str | Clear mode: auto, always, never；默认 `auto`；示例 auto、always、never |
| `dest` | 可选 | str | Destination address；默认 `999999999999`；示例 999999999999 |
| `file-id` | 可选 | int | File ID；默认 `1`；示例 1 |
| `file-type` | 可选 | int | File type (0=clear, 1=CCO module, 2=slave module, 3=collector)；默认 `1`；示例 1、2 |
| `final-ack-timeout` | 可选 | str | Final segment ACK timeout；默认 `30s`；示例 30s |
| `finish` | 可选 | str | Finish mode: none, progress, report；默认 `none`；示例 none、progress、report |
| `finish-timeout` | 可选 | str | Finish progress poll timeout；默认 `60s`；示例 60s |
| `interval` | 可选 | str | Inter-frame delay；默认 `0`；示例 0ms、100ms |
| `no-cache` | 可选 | bool | Force rebuild .upg_cache |
| `no-resume` | 可选 | bool | Disable resume |
| `proto` | 可选 | str | Protocol (default csg; aliases csg2016, csg_2016)；默认 `csg`；示例 csg、csg2016 |
| `resume` | 可选 | bool | Enable resume from E8000703 query；默认 `True` |
| `retries` | 可选 | int | Retries per segment；默认 `3`；示例 3 |
| `segment-size` | 可选 | int | Segment size (128/256/512/1024)；默认 `1024`；示例 1024、512 |
| `seq` | 可选 | int | Starting SEQ value；默认 `1`；示例 1 |
| `timeout` | 可选 | str | Alias for ack-timeout；示例 5s |
| `timeout-min` | 可选 | int | File transfer timeout in minutes；默认 `30`；示例 30 |
| `to` | 可选 | str | Serial connection name; omitted when exactly one connection is active；示例 cco |

---

## /var

**功能**：会话变量管理（set/get/export 等）

### 子命令

#### `/var set`

**功能**：设置变量

**用法**：`/var set <value> <name> [type]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `value` | 必填 | str | 变量值 |
| `name` | 推荐 | str | 变量名 |
| `type` | 可选 | choice | 变量类型；默认 `string`；示例 string、integer、decimal、boolean |

#### `/var get`

**功能**：读取变量

**用法**：`/var get <name>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 变量名 |

#### `/var show`

**功能**：显示全部变量

**用法**：`/var show [json]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `json` | 可选 | bool | 以 JSON 格式输出 |

#### `/var delete`

**功能**：删除变量

**用法**：`/var delete <name>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `name` | 推荐 | str | 变量名 |

#### `/var clear`

**功能**：清空全部变量

**用法**：`/var clear`

#### `/var export`

**功能**：导出变量到 YAML

**用法**：`/var export <file>`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `file` | 必填 | str | YAML文件路径 |

#### `/var import`

**功能**：从 YAML 导入变量

**用法**：`/var import <file> [mode]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `file` | 必填 | str | YAML文件路径 |
| `mode` | 可选 | choice | 导入模式；默认 `merge`；示例 merge、replace |

---

## /wait-frame

**功能**：监听串口，拆帧解码并按 expect 条件匹配响应

### 子命令

#### `/wait-frame listen`

**功能**：等待并匹配串口帧

**用法**：`/wait-frame listen 〔to〕 [expect] [expect.afn] [expect.di] [expect.dir] [proto] [timeout]`

| 参数 | 必填/可选 | 类型 | 说明 |
|------|-----------|------|------|
| `to` | 推荐 | str | Serial connection target；示例 default、cco |
| `expect` | 可选 | str | Full expect JSON: {"all":[{"path":"$.afn","op":"eq","value":"04"}]} |
| `expect.afn` | 可选 | str | Expected AFN value |
| `expect.di` | 可选 | str | Expected DI value |
| `expect.dir` | 可选 | choice | Expected direction；示例 uplink、downlink |
| `proto` | 可选 | choice | Protocol to decode (auto-detect if omitted)；示例 csg、dlt645 |
| `timeout` | 可选 | int | Max wait time in ms；默认 `5000`；示例 5000、10000 |

---
