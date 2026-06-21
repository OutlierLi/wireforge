"""公共 API — 执行命令、校验参数、列出命令。"""

from __future__ import annotations

from typing import Any

from console.command import registry
from console.handler import CmdResult

# 触发注册
import console.handler  # noqa: F401


def exec_cmd(name: str, args: dict[str, Any]) -> CmdResult:
    """执行命令。返回 CmdResult。自动记录到 log/console.log。"""
    from protocol_tool.utils.logger import log_console

    handler = registry.handler(name)
    if not handler:
        result = CmdResult(success=False, command=name, error=f"unknown command: {name}")
        log_console(command=name, args=args, success=False, error=result.error)
        return result

    errors = registry.validate_args(name, args)
    if errors:
        result = CmdResult(success=False, command=name, error="; ".join(errors))
        log_console(command=name, args=args, success=False, error=result.error)
        return result

    result = handler(args)
    log_console(command=name, args=args, success=result.success,
                path=result.path, frame_hex=result.frame_hex,
                output=result.output if result.success else None,
                error=result.error if not result.success else "")
    return result


def list_cmds() -> list[dict]:
    """列出所有命令定义。"""
    return [c.to_dict() for c in registry.all_commands()]


def get_cmd(name: str) -> dict | None:
    """获取单个命令定义。"""
    cmd = registry.get(name)
    return cmd.to_dict() if cmd else None
