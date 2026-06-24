"""命令行模块 — 通过 command-runtime 分发，返回 protocol-tui.v1 响应。

所有前端通过此层调用，runtime 管理多轮交互状态。
"""

from __future__ import annotations

from typing import Any

from console.command import registry
from console.runtime import runtime


def exec_cmd(name: str, args: dict[str, Any]) -> dict:
    """执行命令。返回 protocol-tui.v1 格式 dict。

    { schema, status, data?, error?, detail?, interaction_id? }
    """
    from protocol_tool.utils.logger import log_console

    result = runtime.execute(name, args)
    log_console(command=name, args=args, result=result)
    return result


def exec_text(text: str, args: dict[str, Any] | None = None) -> dict:
    """执行 shell 风格命令文本。"""
    from protocol_tool.utils.logger import log_console

    result = runtime.execute_text(text, args or {})
    log_console(command=text, args=args or {}, result=result)
    return result


def continue_cmd(interaction_id: str, args: dict[str, Any]) -> dict:
    """继续多轮交互。"""
    from protocol_tool.utils.logger import log_console

    result = runtime.continue_interaction(interaction_id, args)
    log_console(command=f"continue:{interaction_id}", args=args, result=result)
    return result


def cancel_cmd(interaction_id: str) -> dict:
    """取消交互。"""
    return runtime.cancel(interaction_id)


def complete_cmd(prefix: str = "", command: str = "") -> dict:
    """请求命令/参数补全。"""
    return runtime.complete(prefix=prefix, command=command)


def list_cmds() -> list[dict]:
    return [c.to_dict() for c in registry.all_commands()]


def get_cmd(name: str) -> dict | None:
    cmd = registry.get(name)
    return cmd.to_dict() if cmd else None
