"""命令行模块 — 纯命令分发，不做业务逻辑，不做参数校验。

流程:
  命令名 + args → registry.resolve → import 业务模块 → handler(args) → result dict
  收发 JSON 记录到 log/console.log
"""

from __future__ import annotations

from typing import Any

from console.command import registry


def exec_cmd(name: str, args: dict[str, Any]) -> dict:
    """执行命令，返回业务模块的 result dict。

    result 格式:
      { success: bool, data?: {}, error?: str, detail?: {} }
    """
    from protocol_tool.utils.logger import log_console

    fn = registry.resolve(name)
    if not fn:
        result = {"success": False, "error": f"unknown command: {name}"}
        log_console(command=name, args=args, result=result)
        return result

    try:
        result = fn(args)
    except Exception as e:
        result = {"success": False, "error": str(e)}

    log_console(command=name, args=args, result=result)
    return result


def list_cmds() -> list[dict]:
    return [c.to_dict() for c in registry.all_commands()]


def get_cmd(name: str) -> dict | None:
    cmd = registry.get(name)
    return cmd.to_dict() if cmd else None
