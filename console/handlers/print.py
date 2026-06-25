"""/print 命令处理器 — 打印文本，支持 ${变量} 引用。

用法:
  /print "当前协议：${protocol}"
  /print ${frame}
  /print '文本：${var}' --raw
"""

from __future__ import annotations

import json
from typing import Any

from console.response import ok, fail
from console.variable_store import store as var_store


def handle(args: dict[str, Any]) -> dict:
    # 获取要打印的文本：优先 --text，其次位置参数拼接
    text = args.get("text", "")
    if not text:
        positional = args.get("_", [])
        text = " ".join(str(x) for x in positional)

    if not text:
        return fail("缺少要打印的文本。用法: /print \"文本\" 或 /print ${var}")

    raw = args.get("raw", False)
    if raw:
        return ok({"output": text, "raw": True})

    # 解析 ${variable} 引用
    resolved = resolve_text(text)
    return ok({"output": resolved, "raw": False})


def resolve_text(text: str) -> str:
    """解析文本中的 ${name} / ${object.field} 引用。"""
    import re
    ref_re = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}")

    refs = ref_re.findall(text)
    if not refs:
        return text

    result = text
    for ref_path in refs:
        try:
            val = var_store.get_value(ref_path)
            if isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            result = result.replace(f"${{{ref_path}}}", str(val))
        except Exception:
            pass  # 变量不存在时保持原文本
    return result
