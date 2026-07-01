"""/time 命令 — 开关串口 TX/RX 终端显示的时间戳前缀。

用法:
  /time on     # 打开时间戳
  /time off    # 关闭时间戳
  /time        # 查看当前状态
"""

from __future__ import annotations

from typing import Any

from console.response import ok, fail


def handle(args: dict[str, Any]) -> dict:
    from wireforge_serial.logger import get_show_timestamp, set_show_timestamp

    sub = str(args.get("sub") or "").strip().lower()
    if not sub:
        pos = args.get("_") or []
        if pos:
            sub = str(pos[0]).strip().lower()

    if sub == "on":
        set_show_timestamp(True)
        return ok({"timestamp": "on", "enabled": True})

    if sub == "off":
        set_show_timestamp(False)
        return ok({"timestamp": "off", "enabled": False})

    if sub:
        return fail(
            "unknown sub-command",
            detail={"hint": "use /time on or /time off", "sub": sub},
        )

    enabled = get_show_timestamp()
    return ok({"timestamp": "on" if enabled else "off", "enabled": enabled})
