"""/help 命令处理器 — 显示命令和子命令的描述与参数。

用法:
  /help              → 列出所有命令
  /help /serial      → /serial 命令详情
  /help "/serial open" → /serial open 子命令详情
"""

from __future__ import annotations

from typing import Any

from console.command import registry
from console.response import ok, fail


def handle(args: dict[str, Any]) -> dict:
    target = args.get("target", args.get("_", [""])[0] if args.get("_") else "")
    target = str(target).strip().strip('"').strip("'")

    if not target:
        return _list_all()

    # 解析 /command 或 "/command sub"
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
            item["sub_commands"] = [
                {"name": f"/{cmd.name} {s}", "desc": d}
                for s, d in cmd.sub_commands.items()
            ]
        items.append(item)
    return ok({"commands": items, "hint": "use /help /command for details"})


def _show_cmd(cmd) -> dict:
    params = []
    for key, meta in sorted(cmd.params.items()):
        if key == "*":
            continue
        p = {
            "name": f"--{key}",
            "type": meta.get("type", "str"),
            "required": meta.get("required", False),
            "examples": meta.get("examples", []),
        }
        if meta.get("note"):
            p["note"] = meta["note"]
        if meta.get("desc"):
            p["desc"] = meta["desc"]
        params.append(p)

    result = {
        "command": f"/{cmd.name}",
        "desc": cmd.desc,
        "params": params,
    }
    if cmd.sub_commands:
        result["sub_commands"] = [
            {"name": f"/{cmd.name} {s}", "desc": d}
            for s, d in cmd.sub_commands.items()
        ]
    return ok(result)


def _show_sub(cmd, sub_name: str) -> dict:
    sub_desc = cmd.sub_commands.get(sub_name, "")
    if not sub_desc:
        return fail(f"unknown sub-command: {sub_name} for /{cmd.name}")

    # 子命令继承父命令的参数
    params = []
    for key, meta in sorted(cmd.params.items()):
        if key in ("*", "sub"):
            continue
        p = {
            "name": f"--{key}",
            "type": meta.get("type", "str"),
            "required": meta.get("required", False),
            "examples": meta.get("examples", []),
        }
        if meta.get("desc"):
            p["desc"] = meta["desc"]
        params.append(p)

    return ok({
        "command": f"/{cmd.name} {sub_name}",
        "desc": sub_desc,
        "params": params,
    })
