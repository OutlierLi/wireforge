"""/delay 命令处理器 — 延时等待。

用法:
  /delay 100          # 100ms
  /delay 500ms        # 500ms
  /delay 2s           # 2 秒
  /delay 1.5s         # 1.5 秒
  /delay --value=100  # 100ms
  /delay --value=2s   # 2 秒

默认单位 ms，支持 s 后缀。
"""

from __future__ import annotations

import re
import time
from typing import Any

from console.response import ok, fail

# 解析: 数字 + 可选单位 (ms/s)
_DURATION_RE = re.compile(r"^(\d+\.?\d*)\s*(ms|s)?$", re.IGNORECASE)


def handle(args: dict[str, Any]) -> dict:
    # 获取时长：--value 参数 或 第一个位置参数
    raw = args.get("value", "")
    if not raw:
        positional = args.get("_", [])
        if positional:
            raw = str(positional[0])
    raw = str(raw).strip().strip('"').strip("'")

    if not raw:
        return fail("缺少时长。用法: /delay 100 或 /delay 2s 或 /delay --value=500ms")

    m = _DURATION_RE.match(raw)
    if not m:
        return fail(
            f"无法解析时长 '{raw}'。用法: /delay 100 (ms) 或 /delay 2s",
            detail={"hint": "支持格式: 100, 500ms, 2s, 1.5s"},
        )

    value = float(m.group(1))
    unit = (m.group(2) or "ms").lower()

    if unit == "s":
        seconds = value
    else:
        seconds = value / 1000.0

    if seconds < 0:
        return fail("时长不能为负数。")

    if seconds > 300:
        return fail(f"时长 {seconds:.1f}s 超过最大限制 300s。")

    start = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - start

    return ok({
        "requested": raw,
        "seconds": round(seconds, 3),
        "elapsed_ms": round(elapsed * 1000, 1),
        "elapsed": f"{elapsed*1000:.0f}ms",
    })
