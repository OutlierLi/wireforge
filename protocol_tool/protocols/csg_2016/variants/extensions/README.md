# CSG 2016 扩展报文

本目录存放 **扩展变体 YAML**，由 `protocol_extend_run` MCP 或手工添加。

- 编译器通过 `variants/**/*.yaml` 自动加载，**不修改** `afn_payloads.yaml`
- 首版仅支持 AFN 00–07 下新增 DI
- 文件名规范：`{AFN}_{DI}.yaml`（AFN 两位十六进制，DI 为 8 位十六进制且以 E8 开头，例 `03_E80304F5.yaml`）

写入后运行：

```bash
python3 scripts/bootstrap_protocol_cache.py
```
