# Protocol Tool — 协议解析和构造框架

YAML 驱动的协议解析与构造框架。支持 DL/T 645-2007、CSG 2016、Q/GDW 10376.2-2019 (NG) 等电力通信协议。

**核心理念**：YAML 定义 → 编译器 → IR (JSON) → 统一 Runtime。新增协议只需编写 YAML，无需修改任何 Python 代码。

---

## 快速开始

### 安装

```bash
cd wireforge
pip install -e .
```

或者用 uv：

```bash
uv sync
```

### 普通终端控制台

不需要 TUI，也不接管鼠标或全屏缓冲区，适合 Windows Terminal、PowerShell、cmd 和普通 SSH 终端。

开发环境直接运行：

```bash
python3 -m console.terminal
```

Windows 可使用：

```powershell
py -m console.terminal
```

安装后也可以运行脚本入口：

```bash
wireforge-terminal
```

进入后使用现有命令，例如：

```text
/help
/serial ports
/serial connect --name cco --port COM3 --baudrate 9600
/serial use --name cco
/serial send --hex "68 00 16"
/exit
```

### OpenCode MCP 服务

WireForge 提供一个面向 Agent 的 MCP Server，用于处理“自然语言 → 协议任务 → JSON 请求 → 执行结果”。MCP 内部维护可恢复状态机，不要求 Agent 拼接 `/build ...` 或 `/serial ...` 命令文本。

直接启动：

```bash
python3 scripts/python/wireforge_mcp_server.py
```

Windows：

```powershell
py scripts\python\wireforge_mcp_server.py
```

安装后也可以使用脚本入口：

```bash
wireforge-mcp-server
```

OpenCode MCP 配置示例：

```json
{
  "mcp": {
    "wireforge": {
      "type": "local",
      "command": ["python3", "scripts/python/wireforge_mcp_server.py"],
      "enabled": true
    }
  }
}
```

暴露工具：

- `protocol_task_run`

调用方式：

```json
{
  "raw_input": "构造 dlt645 功能码 13 address AAAAAAAAAAAA"
}
```

若返回 `WAITING_INPUT`，上层 Agent 只需要向用户询问缺失字段，再用同一个 `run_id` 补充：

```json
{
  "run_id": "<run_id>",
  "user_input": {
    "proto": "dlt645",
    "func": "13",
    "address": "AAAAAAAAAAAA"
  }
}
```

每次运行会写入：

```text
agent_protocol_runs/<run_id>/
  raw_input
  context.json
  task_plan.json
  state.json
  events
  result.json
```

同时会追加全局 workflow 日志：

```text
log/agent_protocol_workflow.log
```

每一步都是带时间戳的文本段落，只记录该步骤新增的信息：用户原文、扩展上下文、识别到的任务类型、线性 task plan、底层 build/decode/send 调用、调用结果、等待输入/失败原因和最终结果。

协议知识库来源集中在 `database/protocols/<protocol>/doc` 和 `protocol_tool/protocols`。MCP 进入后会先检索知识库，把最相关的协议文档片段和结构化 YAML 片段放入上下文，再做任务判断、构造/解析和 decode 校验。

重建知识库索引：

```bash
python3 scripts/python/knowledge_kb_cli.py ingest --rebuild
```

### 编译协议

将 YAML 协议定义编译为运行时 IR：

```bash
python3 -m protocol_tool.cli.main compile --protocol dlt645_2007
```

输出：

```
Compiled dlt645_2007 → compiled/dlt645_2007.ir.json
  Frame fields: 9
  Routers: 2
  Messages/Variants: 7
```

支持的协议：`dlt645_2007`、`csg_2016`、`ng_2019`。

### 解析报文

```bash
python3 -m protocol_tool.cli.main decode \
  --protocol dlt645_2007 \
  --hex "FE FE 68 12 34 56 78 90 12 68 91 08 33 34 33 33 58 39 54 43 14 16"
```

输出 JSON 格式的解析结果，含逐字段解析轨迹（`--trace`）。

### 查看路由表

```bash
python3 -m protocol_tool.cli.main inspect routes --protocol dlt645_2007
```

输出：

```
Router: main
  Keys: ['control.func', 'control.dir']
  Fallback: raw
  Routes:
    [17,0]        → read_data_request
    [17,1]        → read_data_response
    [19,0]        → read_address_request
    [19,1]        → read_address_response

Router: read_data_response_di
  Keys: ['di']
  Fallback: raw
  Routes:
    00010000      → daily_freeze_time
    00010001      → monthly_freeze_time
    0001FF00      → forward_active_total_energy
```

### 查看协议概览

```bash
python3 -m protocol_tool.cli.main inspect protocol --protocol dlt645_2007
```

### Python API

```python
from protocol_tool.compiler.pipeline import compile_protocol
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import DecodeEngine

# 1. 编译协议
ir = compile_protocol("protocols/registry.yaml", "dlt645_2007", output_dir="compiled")

# 2. 创建解码引擎
registry = create_builtin_registry()
engine = DecodeEngine(ir, registry)

# 3. 解析报文
frame = bytes.fromhex("FE FE 68 ... 16")
result = engine.decode(frame)

print(result.values)   # 解析出的字段值
print(result.trace)    # 逐字段解析路径
```

---

## 架构

```
                           ┌──────────────────────┐
                           │   YAML 协议定义        │
                           │  registry.yaml        │
                           │  ├── protocol.yaml    │
                           │  ├── frame.yaml       │
                           │  ├── messages/*.yaml  │
                           │  ├── variants/*.yaml  │
                           │  └── types/*.yaml     │
                           └──────────┬───────────┘
                                      │ 编译
                                      ▼
                           ┌──────────────────────┐
                           │   Compiler (编译器)    │
                           │  loader               │
                           │  frame_compiler       │
                           │  message_compiler     │
                           │  router_builder       │
                           │  validator            │
                           │  pipeline             │
                           └──────────┬───────────┘
                                      │ 输出
                                      ▼
                           ┌──────────────────────┐
                           │   ProtocolIR (JSON)   │
                           │  FrameNode            │
                           │  RouterNode[]         │
                           │  LeafNode[]           │
                           │  BuildPlan[]          │
                           └──────────┬───────────┘
                                      │ 运行时加载
                                      ▼
              ┌───────────────────────────────────────────┐
              │              Runtime (运行时)               │
              │                                            │
              │  DecodeReader    DecodeContext              │
              │  (字节流+位置)    (解析值+Trace)              │
              │                                            │
              │  ExecutionStack   Router                   │
              │  (嵌套追踪)       (key_paths→route_table)    │
              │                                            │
              │  DecodeEngine / BuildEngine                │
              │  (遍历帧字段 → codec.decode/encode)          │
              └──────────────┬────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │      Codec Registry          │
              │  (算法与协议完全解耦)           │
              │                              │
              │  uint8  uint16_le  bcd       │
              │  bitset  const  checksum     │
              │  routed_payload  transform   │
              │  hex  bytes  ascii  struct   │
              │  array  enum                 │
              └──────────────────────────────┘
```

### 数据流

#### 解析路径（Decode）

```
wire bytes
  → 加载 protocol.ir.json
  → 遍历 FrameNode.fields
     → const/uint/bcd: codec.decode(field, reader, context)
     → routed_payload:
        1. 读原始字节（length_from 确定长度）
        2. 应用线变换（add_33h / sub_33h）
        3. Router.resolve(context) → 找到 target LeafNode
        4. push StackFrame → 解码 LeafNode.fields → pop
     → checksum: 计算 cover 的校验和，与 wire 值比对
  → 输出 DecodeResult
```

#### 构造路径（Build）

```
message_id + values
  → BuildPlan 确定路由链
  → 遍历 FrameNode.fields
     → const/uint/bcd: codec.encode(field, value, writer, context)
     → routed_payload:
        1. 根据 message_id 定位 LeafNode
        2. 编码 LeafNode.fields → 子 writer
        3. 应用线变换
        4. 写入主 writer
     → checksum: 计算 cover 的校验和并写入
  → 输出完整帧 bytes
```

### IR 数据结构

```python
@dataclass(frozen=True)
class FieldNode:
    """帧或消息中的一个字段"""
    id: str                           # 唯一标识
    name: str                         # 字段名
    type_ref: str                     # Codec 注册表键（"uint8", "bcd", "routed_payload"...）
    params: dict[str, Any]            # 编解码器参数
    length: int | None                # 固定长度
    length_from: str | None           # 长度引用另一字段
    length_adjust: int                # 长度调整量
    transforms: tuple[TransformSpec]  # 线变换
    condition: ConditionSpec | None   # 条件存在

@dataclass(frozen=True)
class RouterNode:
    """路由器：选择下一个 IR Node（不消费字节）"""
    id: str
    key_paths: tuple[str, ...]        # 路由键路径 ["control.func", "control.dir"]
    route_table: dict[str, str]       # 序列化键 → target_node_id
    fallback_policy: Literal["error", "raw", "preserve_payload"]

@dataclass(frozen=True)
class LeafNode:
    """终端节点：消息/变体的载荷字段"""
    id: str
    name: str
    fields: tuple[FieldNode, ...]

@dataclass(frozen=True)
class ProtocolIR:
    """顶层编译产物，运行时唯一加载对象"""
    version: int
    protocol: str
    frame: FrameNode
    routers: dict[str, RouterNode]
    leaves: dict[str, LeafNode]
    build_plans: dict[str, BuildPlan]
```

### Router 抽象（核心创新）

Router 只做路由选择，不消费字节。类似网络路由表：

| 网络路由  | 协议解析 |
|-----------|---------|
| 路由表    | `route_table` |
| 目的地址  | 控制码、AFN、DI 等已解析字段 |
| 下一跳    | 下一个 IR Node / Schema |
| 转发数据包 | 用该 Node 继续消费后续字节 |
| 默认路由  | `fallback`（如 `raw_remaining`） |
| 路由冲突  | 两个 schema 命中同一个 key |

示例：

```
645 协议:
  key = [control.func=0x11, control.dir=1] → read_data_response schema
  key = [di=00010000]                       → daily_freeze_time schema

CSG 协议:
  key = [control.func=0x00]  → afn00_ack schema
  key = [afn=0x0C, di=E802]  → afn0c_e802 schema
```

### Codec 注册表（算法与协议解耦）

```python
codec_registry = {
    "uint8":       UIntCodec(1),
    "uint16_le":   UIntCodec(2, byte_order="little"),
    "bcd":         BcdCodec(),
    "bitset":      BitSetCodec(),
    "sum8":        ChecksumCodec("sum8"),
    "crc16_modbus": ChecksumCodec("crc16_modbus"),
    "add_33h":     Add33HTransform(),
    "sub_33h":     Sub33HTransform(),
    "routed_payload": RoutedPayloadCodec(),
    ...
}
```

IR 中只引用算法名，运行时从注册表解析。新增协议只需在 YAML 中引用已有算法名，或注册新的算法实现。

---

## 项目结构

```
protocol_tool/
├── ir/                        # IR 数据结构（纯 dataclass）
│   └── nodes.py               # FieldNode, RouterNode, LeafNode, FrameNode, ProtocolIR
├── compiler/                  # YAML → IR 编译
│   ├── loader.py              # YAML 文件加载与发现
│   ├── resolver.py            # $ref 解析, 类型解析
│   ├── frame_compiler.py      # frame.yaml → FrameNode
│   ├── message_compiler.py    # messages/*.yaml → LeafNode
│   ├── variant_compiler.py    # variants/*.yaml → LeafNode
│   ├── router_builder.py      # 构建 route_table
│   ├── validator.py           # 交叉校验
│   └── pipeline.py            # 编排完整编译流程
├── runtime/                   # 运行时引擎
│   ├── reader.py              # DecodeReader（字节流 + 位置 + 边界）
│   ├── context.py             # DecodeContext, BuildContext, TraceEvent
│   ├── stack.py               # ExecutionStack（嵌套结构追踪）
│   ├── router.py              # Router.resolve(ctx) → target_node_id
│   └── engine.py              # DecodeEngine, BuildEngine
├── codecs/                    # 算法/编解码器注册表
│   ├── __init__.py            # CodecRegistry, create_builtin_registry()
│   ├── base.py                # FieldCodec ABC, ByteWriter
│   ├── uint.py                # UIntCodec (8/16/24/32/48 le/be)
│   ├── bcd.py                 # BcdCodec, BcdNumericCodec
│   ├── bitset.py              # BitSetCodec
│   ├── const.py               # ConstCodec, ConstRepeatCodec
│   ├── bytes_codec.py         # HexCodec, BytesCodec, AsciiCodec
│   ├── checksum.py            # ChecksumCodec (sum8, xor8, crc16_modbus, crc16_ccitt, crc8)
│   ├── struct_codec.py        # StructCodec
│   ├── array_codec.py         # ArrayCodec
│   ├── enum_codec.py          # EnumCodec
│   ├── routed.py              # RoutedPayloadCodec（触发 Router）
│   └── transforms.py          # 线变换 (reverse_bytes, add_33h, sub_33h)
├── protocols/                 # 协议 YAML 定义
│   ├── registry.yaml          # 顶层协议注册表
│   ├── dlt645_2007/
│   │   ├── protocol.yaml      # 协议入口 + Router 声明
│   │   ├── frame.yaml         # 帧结构
│   │   ├── types/shared.yaml  # 类型定义
│   │   ├── messages/          # 按控制码区分
│   │   └── variants/          # 按 DI 区分
│   ├── csg_2016/
│   │   ├── protocol.yaml
│   │   ├── frame.yaml
│   │   ├── types/shared.yaml
│   │   └── messages/
│   └── ng_2019/
│       ├── protocol.yaml
│       ├── frame.yaml
│       ├── types/shared.yaml
│       └── messages/
├── cli/                       # protocolctl 命令行
│   └── main.py                # Typer 入口
└── utils/
    ├── hex.py                 # 十六进制规范化
    ├── yaml_loader.py         # YAML 安全加载
    └── graph.py               # 路由图 DOT 生成
```

---

## CLI 命令参考

### `protocolctl compile`

```bash
# 编译单个协议
protocolctl compile --protocol dlt645_2007

# 指定输出目录
protocolctl compile --protocol csg_2016 --output ./dist
```

### `protocolctl decode`

```bash
# 基本解析
protocolctl decode --protocol dlt645_2007 --hex "FE FE 68 ... 16"

# 输出格式：json（默认）、tree、yaml
protocolctl decode -p dlt645_2007 --hex "..." --format tree

# 显示解析轨迹
protocolctl decode -p dlt645_2007 --hex "..." --trace
```

### `protocolctl build`

```bash
# 构造报文
protocolctl build -p dlt645_2007 \
  --message read_data_response \
  --values '{"di": "00010000", "freeze_year": "25", "freeze_month": "06"}'
```

### `protocolctl inspect`

```bash
# 查看路由表
protocolctl inspect routes --protocol dlt645_2007

# 筛选特定路由器
protocolctl inspect routes -p dlt645_2007 --router read_data_response_di

# 生成路由图
protocolctl inspect graph -p dlt645_2007 --output routes.dot

# 查看协议概览
protocolctl inspect protocol -p dlt645_2007
```

---

## 如何新增协议

### 新增 DI 变体（已有协议）

```bash
# 1. 创建 variants/read_data_response/XXXXXXXX_xxx.yaml
cat > protocols/dlt645_2007/variants/read_data_response/00010002_xxx.yaml << 'EOF'
kind: variant
id: dlt645_2007.read_data_response.xxx
router: read_data_response_di

match:
  di: "00010002"

body:
  type: struct
  fields:
    - name: field_a
      type: bcd
      length: 2
    - name: field_b
      type: uint8
EOF

# 2. 重新编译
protocolctl compile --protocol dlt645_2007
```

### 新增控制码消息

```bash
# 1. 创建 messages/write_data.yaml
cat > protocols/dlt645_2007/messages/write_data.yaml << 'EOF'
messages:
  - kind: message
    id: write_data_request
    router: main
    match:
      control.func: 0x15
      control.dir: 0
    body:
      type: struct
      fields:
        - name: di
          type: hex
          length: 4
        - name: write_data
          type: bytes
          length_from: length
          length_adjust: -1
EOF

# 2. 重新编译
protocolctl compile --protocol dlt645_2007
```

### 新增完整协议

```bash
# 1. 创建目录结构
mkdir -p protocols/new_protocol/{types,messages,variants}

# 2. 编写 protocol.yaml
cat > protocols/new_protocol/protocol.yaml << 'EOF'
id: new_protocol
name: "New Protocol"
frame_ref: frame.yaml
sources:
  messages: "messages/**/*.yaml"
  variants: "variants/**/*.yaml"
routers:
  main:
    kind: frame_router
    keys: [control.func]
    fallback: raw
EOF

# 3. 编写 frame.yaml（定义帧结构）
# 4. 编写消息/变体 YAML
# 5. 在 registry.yaml 中注册
# 6. 编译
protocolctl compile --protocol new_protocol
```

---

## 设计原则

1. **协议定义是数据，不是代码**。所有协议行为通过 YAML 声明，编译器转换为 IR。
2. **Router 是路由选择，不是解析函数**。路由只查表选节点，目标节点才消费字节。
3. **Codec 与协议解耦**。算法注册表独立于协议定义，新增算法只需注册。
4. **IR 是运行时唯一依赖**。运行时只加载 `.ir.json`，不解析 YAML。
5. **Trace 是一等公民**。每次解析自动记录逐字段路径，方便调试和审计。
6. **构建与解析互为镜像**。DecodeEngine 和 BuildEngine 共享同一套 IR 和 Codec。
