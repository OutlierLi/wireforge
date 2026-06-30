# CSG 2016 扩展报文

本目录存放 **Agent 新增** 的扩展变体 YAML，由 `protocol_extend_run` MCP 从 C 结构体生成。

- 内置报文 payload 见 [`../c_struct/`](../c_struct/) → 生成到 [`../payloads/`](../payloads/)
- 编译器通过 `variants/**/*.yaml` 自动加载
- 文件名规范：`{AFN}_{DI}.yaml`

写入后运行：

```bash
python3 scripts/bootstrap_protocol_cache.py
```
