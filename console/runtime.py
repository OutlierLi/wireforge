"""command-runtime — 统一命令执行引擎。

所有前端 (CLI / TUI / Web) 通过此层调用业务模块。
runtime 管理多轮交互状态，返回 protocol-tui.v1 契约响应。
"""

from __future__ import annotations

import shlex, uuid
from typing import Any

from console.command import registry
from console.protocol import (
    Interaction,
    response_success, response_need_input, response_need_disambiguation,
    response_invalid_argument, response_no_route, response_execution_error,
    response_session_closed,
)


class Runtime:
    """命令运行时 — 单例。"""

    def __init__(self):
        self._interactions: dict[str, Interaction] = {}

    def execute(self, command: str, args: dict[str, Any]) -> dict:
        """执行命令。返回 protocol-tui.v1 响应。"""
        command = command.lstrip("/")
        args = _normalize_args(args)
        fn = registry.resolve(command)
        if not fn:
            return response_no_route(f"unknown command: {command}")

        try:
            result = fn(args)
        except Exception as e:
            return response_execution_error(str(e))

        # 将业务模块的 dict 映射为协议响应
        return self._map_result(command, args, result)

    def continue_interaction(self, interaction_id: str, args: dict[str, Any]) -> dict:
        """继续多轮交互。"""
        ix = self._interactions.get(interaction_id)
        if not ix:
            return response_session_closed(interaction_id)

        merged = {**ix.args, **_normalize_args(args)}
        return self.execute(ix.command, merged)

    def cancel(self, interaction_id: str) -> dict:
        """取消交互。"""
        self._interactions.pop(interaction_id, None)
        return response_session_closed(interaction_id)

    def execute_text(self, text: str, args: dict[str, Any] | None = None) -> dict:
        """解析前端命令文本并执行。

        command-runtime 只解析通用 shell 风格参数，不解释协议语义。
        """
        command, parsed_args = parse_command_text(text)
        merged = {**parsed_args, **(args or {})}
        return self.execute(command, merged)

    def complete(self, prefix: str = "", command: str = "") -> dict:
        """返回命令/参数补全候选。"""
        prefix = prefix or ""
        command = command.lstrip("/")
        completions: list[dict[str, Any]] = []

        if not command:
            raw = prefix[1:] if prefix.startswith("/") else prefix
            for name in registry.names():
                if not raw or name.startswith(raw):
                    completions.append({
                        "kind": "command",
                        "value": f"/{name}",
                        "label": f"/{name}",
                    })
        else:
            cmd = registry.get(command)
            if cmd:
                raw = prefix[2:] if prefix.startswith("--") else prefix
                for key, meta in cmd.params.items():
                    if key == "*":
                        continue
                    if not raw or key.startswith(raw):
                        item = {
                            "kind": "argument",
                            "value": f"--{key}",
                            "label": f"--{key}",
                            "type": meta.get("type", "str"),
                            "required": meta.get("required", False),
                            "description": meta.get("desc", ""),
                        }
                        if "examples" in meta:
                            item["examples"] = meta["examples"]
                        if "default" in meta:
                            item["default"] = meta["default"]
                        completions.append(item)

        return response_success({"completions": completions})

    # ── 映射 ──

    def _map_result(self, cmd: str, args: dict, result: dict) -> dict:
        """将业务模块 dict 映射到协议响应。"""
        if result.get("success"):
            data = result.get("data", {})
            # 检测是否需要继续交互 (如 build resolve 后需要补充参数)
            return response_success(data)

        error = result.get("error", "")
        detail = result.get("detail", {})

        # missing required params → need_input
        missing = detail.get("missing", [])
        if missing:
            iid = self._start_interaction(cmd, args)
            schema = []
            for m in missing:
                schema.append({
                    "key": m["key"], "type": m.get("type", "str"),
                    "examples": m.get("examples", []),
                    "desc": m.get("desc", ""),
                    "required": True,
                })
            return response_need_input(iid, schema, hint=detail.get("hint", ""))

        # route not found / ambiguous
        if "route" in error.lower() or "no route" in error.lower():
            path = result.get("path", "") or args.get("path", "")
            return response_no_route(error, path)

        # disambiguation needed
        if "multiple routes" in error.lower() or "disambiguate" in error.lower():
            # extract available options from error
            candidates = _extract_candidates(error)
            key = _extract_key(error)
            return response_need_disambiguation(candidates, key=key)

        # generic execution error
        return response_execution_error(error, detail)

    def _start_interaction(self, cmd: str, args: dict) -> str:
        iid = str(uuid.uuid4())[:8]
        self._interactions[iid] = Interaction(id=iid, command=cmd, args=args)
        return iid


# ── helpers ───────────────────────────────────────────────────────────

def _extract_candidates(error: str) -> list[dict]:
    """从错误消息提取候选路径: "Available: ['E8020404', 'E8020405']" """
    import re
    m = re.search(r"Available:\s*\[([^\]]+)\]", error)
    if m:
        items = [x.strip().strip("'\"") for x in m.group(1).split(",")]
        return [{"value": i, "label": i} for i in items]
    return []


def _extract_key(error: str) -> str:
    """从错误消息提取歧义消除键: "Provide di to disambiguate" → "di" """
    import re
    m = re.search(r"Provide\s+(\w+)\s+to disambiguate", error)
    return m.group(1) if m else ""


def parse_command_text(text: str) -> tuple[str, dict[str, Any]]:
    """Parse `/cmd --key=value --flag positional` into command + args.

    Positional tokens are preserved as `_` so clients can still display or
    forward them without pretending they have protocol meaning.
    """
    parts = shlex.split(text.strip())
    if not parts:
        return "", {}

    command = parts[0].lstrip("/")
    args: dict[str, Any] = {}
    positional: list[str] = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            raw = token[2:]
            if "=" in raw:
                key, value = raw.split("=", 1)
                args[key] = value
            elif i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                args[raw] = parts[i + 1]
                i += 1
            else:
                args[raw] = True
        else:
            positional.append(token)
        i += 1
    if positional:
        args["_"] = positional
    return command, _normalize_args(args)


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "protocol": "proto",
        "direction": "dir",
    }
    normalized: dict[str, Any] = {}
    for key, value in args.items():
        normalized[aliases.get(key, key)] = value
    return normalized


# ── 全局单例 ──────────────────────────────────────────────────────────

runtime = Runtime()
