# CSG 2016 扩展报文

本目录存放 **扩展变体 YAML**，由 `protocol_extend_run` MCP 或手工添加。

- 编译器通过 `variants/**/*.yaml` 自动加载，**不修改** `afn_payloads.yaml`
- 首版仅支持 AFN 00–07 下新增 DI
- 文件名建议：`{afn}_{di}_{slug}.yaml`

写入后运行：

```bash
python3 scripts/bootstrap_protocol_cache.py
```
