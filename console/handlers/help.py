"""/help 命令处理器 — 显示命令和子命令的描述与参数。

用法:
  /help              → 列出所有命令
  /help /serial      → /serial 命令详情
  /help "/serial open" → /serial open 子命令详情
"""

from __future__ import annotations

from typing import Any

from console.command import registry
from console.command_schema import (
    effective_params,
    list_sub_commands,
    params_to_help_list,
    sub_command_desc,
)
from console.response import ok, fail


def handle(args: dict[str, Any]) -> dict:
    target = args.get("target", args.get("_", [""])[0] if args.get("_") else "")
    target = str(target).strip().strip('"').strip("'")

    if not target:
        return _list_all()

    parts = target.lstrip("/").split()
    cmd_name = parts[0]
    sub_name = parts[1] if len(parts) > 1 else ""

    cmd = registry.get(cmd_name)
    if not cmd:
        return fail(f"unknown command: {cmd_name}")

    if sub_name:
        return _show_sub(cmd, sub_name)
    return _show_cmd(cmd)


def _list_all() -> dict:
    items = []
    for cmd in registry.all_commands():
        item = {"name": f"/{cmd.name}", "desc": cmd.desc}
        if cmd.sub_commands:
            item["sub_commands"] = list_sub_commands(cmd)
        items.append(item)
    return ok({"commands": items, "hint": "use /help /command or /help \"/command sub\" for details"})


def _show_cmd(cmd) -> dict:
    result = {
        "command": f"/{cmd.name}",
        "desc": cmd.desc,
        "params": params_to_help_list(cmd.params),
    }
    if cmd.sub_commands:
        result["sub_commands"] = list_sub_commands(cmd)
        result["hint"] = f'use /help "/{cmd.name} <sub>" for sub-command parameters'
    return ok(result)


def _show_sub(cmd, sub_name: str) -> dict:
    if sub_name not in cmd.sub_commands:
        return fail(f"unknown sub-command: {sub_name} for /{cmd.name}")

    desc = sub_command_desc(cmd, sub_name)
    params = params_to_help_list(effective_params(cmd, sub_name))
    recommended = [p["name"] for p in params if p.get("recommended")]

    result: dict[str, Any] = {
        "command": f"/{cmd.name} {sub_name}",
        "desc": desc,
        "params": params,
    }
    if recommended:
        result["recommended"] = recommended
    return ok(result)
