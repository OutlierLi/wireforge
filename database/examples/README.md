# TestPlan 示例（自然语言 → 编排）

本目录存放**如何用自然语言描述测试流程**的 Markdown 示例，供 OpenCode Agent 参考。

每个示例包含：

- 可直接复制给 OpenCode 的提示词
- 测试意图、环境、步骤与期望
- 指向 `database/runs/` 下对应 YAML TestPlan 的链接

| 示例 | 说明 |
|------|------|
| [vendor_code_query.md](vendor_code_query.md) | CCO 查询厂商代码，STA 回复，CCO wait-frame 验证 |

YAML TestPlan 文件仍在 [`../runs/`](../runs/) 目录，由 Agent 编排生成或人工维护。
