"""公共 API — 执行命令、校验参数、列出命令。"""

from __future__ import annotations

from typing import Any

from console.command import registry
from console.handler import CmdResult

# 触发注册
import console.handler  # noqa: F401


def exec_cmd(name: str, args: dict[str, Any]) -> CmdResult:
    """执行命令。返回 CmdResult。"""
    handler = registry.handler(name)
    if not handler:
        return CmdResult(success=False, command=name, error=f"unknown command: {name}")

    errors = registry.validate_args(name, args)
    if errors:
        return CmdResult(success=False, command=name, error="; ".join(errors))

    return handler(args)


def list_cmds() -> list[dict]:
    """列出所有命令定义。"""
    return [c.to_dict() for c in registry.all_commands()]


def get_cmd(name: str) -> dict | None:
    """获取单个命令定义。"""
    cmd = registry.get(name)
    return cmd.to_dict() if cmd else None
