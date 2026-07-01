"""命令树 schema — 子命令参数合并、校验、help/补全辅助。

sub_commands 支持两种格式（向后兼容）:
  - 字符串: "connect": "First-time connection ..."
  - 对象:   "connect": {"desc": "...", "params": {...}}

参数排序: required(0) → recommended(1) → optional(2) → order → name
"""

from __future__ import annotations

from typing import Any

from console.command import Command


DEFAULT_SUB: dict[str, str] = {
    "serial": "ports",
    "auto_rule": "list",
    "build": "build",
    "decode": "decode",
    "route": "resolve",
    "find": "search",
    "delay": "wait",
    "print": "text",
    "help": "show",
    "split": "open",
    "run": "execute",
    "upg": "transfer",
    "wait-frame": "listen",
    "request": "send",
}


def resolve_sub_command(args: dict[str, Any], *, default: str = "") -> str:
    sub = args.get("sub")
    if sub:
        return str(sub)
    pos = args.get("_") or []
    if pos:
        first = str(pos[0])
        if not first.startswith("--"):
            return first
    return default


def _sub_entry(cmd: Command, sub_name: str) -> dict[str, Any]:
    raw = cmd.sub_commands.get(sub_name)
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {"desc": raw, "params": {}}
    if isinstance(raw, dict):
        return raw
    return {}


def sub_command_desc(cmd: Command, sub_name: str) -> str:
    return str(_sub_entry(cmd, sub_name).get("desc", ""))


def has_structured_sub_commands(cmd: Command) -> bool:
    return any(isinstance(v, dict) and v.get("params") is not None for v in cmd.sub_commands.values())


def effective_params(cmd: Command, sub_name: str | None) -> dict[str, Any]:
    base = {k: v for k, v in cmd.params.items() if k not in ("sub", "*")}
    if not sub_name:
        return base
    sub_params = _sub_entry(cmd, sub_name).get("params") or {}
    merged = dict(base)
    merged.update(sub_params)
    return merged


def all_sub_params_union(cmd: Command) -> dict[str, Any]:
    merged: dict[str, Any] = {
        k: v for k, v in cmd.params.items() if k not in ("sub", "*")
    }
    for sub_name in cmd.sub_commands:
        for key, meta in effective_params(cmd, sub_name).items():
            merged.setdefault(key, meta)
    return merged


def param_sort_key(key: str, meta: dict[str, Any]) -> tuple:
    if meta.get("required"):
        rank = 0
    elif meta.get("recommended"):
        rank = 1
    else:
        rank = 2
    order = meta.get("order", 9999)
    if not isinstance(order, int):
        order = 9999
    return (rank, order, key)


def sorted_params(params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items = [
        (key, meta) for key, meta in params.items()
        if key not in ("sub", "*") and isinstance(meta, dict)
    ]
    return sorted(items, key=lambda kv: param_sort_key(kv[0], kv[1]))


def param_value_candidates(meta: dict[str, Any]) -> list[str]:
    """参数值候选：default 优先，再 examples（去重保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    default = meta.get("default")
    if default is not None:
        text = str(default)
        if text not in seen:
            out.append(text)
            seen.add(text)
    for item in meta.get("examples") or []:
        text = str(item)
        if text not in seen:
            out.append(text)
            seen.add(text)
    return out


def bracket_param(key: str, meta: dict[str, Any]) -> str:
    if meta.get("required"):
        return f"<{key}>"
    if meta.get("recommended"):
        return f"〔{key}〕"
    return f"[{key}]"


def format_usage_params(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, meta in sorted_params(params):
        if meta.get("positional"):
            parts.append(f"<{key}>")
        else:
            parts.append(bracket_param(key, meta))
    return " ".join(parts)


def params_to_help_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, meta in sorted_params(params):
        flag = key if meta.get("positional") else f"--{key}"
        p: dict[str, Any] = {
            "name": flag,
            "type": meta.get("type", "str"),
            "required": bool(meta.get("required", False)),
            "examples": meta.get("examples", []),
        }
        if meta.get("recommended"):
            p["recommended"] = True
        if meta.get("positional"):
            p["positional"] = True
        if meta.get("default") is not None:
            p["default"] = meta["default"]
        if meta.get("note"):
            p["note"] = meta["note"]
        if meta.get("desc"):
            p["desc"] = meta["desc"]
        out.append(p)
    return out


def list_sub_commands(cmd: Command) -> list[dict[str, str]]:
    return [
        {"name": f"/{cmd.name} {sub_name}", "desc": sub_command_desc(cmd, sub_name)}
        for sub_name in cmd.sub_commands
    ]


def resolve_effective_sub(cmd: Command, args: dict[str, Any]) -> str:
    if cmd.name == "build":
        if args.get("from_frame") or args.get("from-frame"):
            return "from-frame"
        if args.get("resolve") or args.get("describe") or args.get("schema"):
            return "resolve"
    default_sub = DEFAULT_SUB.get(cmd.name, "")
    return resolve_sub_command(args, default=default_sub)


def validate_args(cmd: Command, args: dict[str, Any]) -> dict[str, Any] | None:
    if not cmd.sub_commands:
        return None

    sub = resolve_effective_sub(cmd, args)
    if sub not in cmd.sub_commands:
        return None

    params = effective_params(cmd, sub)
    if not params:
        return None

    missing: list[dict[str, Any]] = []
    for key, meta in sorted_params(params):
        if not meta.get("required"):
            continue
        if cmd.name == "auto_rule" and sub == "add" and key == "match":
            from console.handlers.auto_rule import has_condition_spec
            if has_condition_spec(args):
                continue
        val = args.get(key)
        if val is None or val == "":
            item: dict[str, Any] = {
                "key": key,
                "type": meta.get("type", "str"),
                "sub_command": sub,
            }
            if meta.get("examples"):
                item["examples"] = meta["examples"]
            if meta.get("desc"):
                item["desc"] = meta["desc"]
            if meta.get("note"):
                item["note"] = meta["note"]
            missing.append(item)

    if not missing:
        return None
    return {
        "success": False,
        "error": "missing required parameter",
        "detail": {"missing": missing, "sub_command": sub},
    }
