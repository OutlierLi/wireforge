"""command-runtime — 统一命令执行引擎。

所有前端入口通过此层调用业务模块。
runtime 管理多轮交互状态，返回 protocol-tui.v1 契约响应。

变量引用解析：
- 执行命令前解析 args 中的 ${name} / ${object.field} 引用。
- 完整引用保留变量类型，模板引用结果统一为 string。
- 命令成功后自动写入 last_result / last_* 结果变量。
- 串口 RX（后台 monitor 或 wait-frame/request）写入 last_rx。
"""

from __future__ import annotations

import re
import shlex
import uuid
from typing import Any

from console.arg_utils import (
    HEX_MERGE_KEYS,
    clean_string_arg,
    merge_bracket_list_value_tail,
    merge_hex_value_tail,
    merge_quoted_value_tail,
)

from console.command import registry
from console.command_schema import (
    effective_params,
    validate_args,
    sorted_params,
)
from console.protocol import (
    Interaction,
    response_success, response_need_input, response_need_disambiguation,
    response_invalid_argument, response_no_route, response_execution_error,
    response_session_closed,
)

# 变量引用模式: ${name} 或 ${name.field.sub}
_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}")


class Runtime:
    """命令运行时 — 单例。"""

    def __init__(self):
        self._interactions: dict[str, Interaction] = {}

    def execute(self, command: str, args: dict[str, Any]) -> dict:
        """执行命令。返回 protocol-tui.v1 响应。"""
        command = command.lstrip("/")
        args = _consume_sub_command(command, _normalize_args(args))

        # 解析变量引用 ${name} / ${object.field}（print 自己处理引用）
        if command != "print":
            args = self._resolve_var_refs(args)

        fn = registry.resolve(command)
        if not fn:
            return response_no_route(f"unknown command: {command}")

        cmd = registry.get(command)
        if cmd:
            schema_error = validate_args(cmd, args)
            if schema_error:
                self._set_error_result(command, schema_error.get("error", ""))
                return self._map_result(command, args, schema_error)

        try:
            result = fn(args)
        except Exception as e:
            self._set_error_result(command, str(e))
            return response_execution_error(str(e))

        # 自动写入结果变量
        self._set_result_vars(command, args, result)

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
        # 解析文本中的变量引用（parse_command_text 后 args 值可能包含 ${...}）
        parsed_args = self._resolve_var_refs(parsed_args)
        merged = {**parsed_args, **(args or {})}
        return self.execute(command, merged)

    def complete(
        self,
        prefix: str = "",
        command: str = "",
        sub: str = "",
        text: str = "",
    ) -> dict:
        """返回命令/参数补全候选（按命令树顺序、已选去重）。"""
        from console.completion import complete_legacy, complete_text

        if text:
            return complete_text(text)
        return complete_legacy(prefix=prefix, command=command, sub=sub)

    # ── 变量引用解析 ─────────────────────────────────────────────────

    def _resolve_var_refs(self, args: dict[str, Any]) -> dict[str, Any]:
        """解析 args 中的 ${name} / ${object.field} 引用。"""
        from console.variable_store import store as var_store

        resolved: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_value(value, var_store)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_value(v, var_store) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    @staticmethod
    def _resolve_value(text: str, var_store) -> Any:
        """解析单个字符串值中的变量引用。

        - 完整引用 "${name}": 保留变量类型
        - 模板引用 "prefix-${name}.yaml": 结果统一为 string
        """
        refs = _VAR_REF_RE.findall(text)
        if not refs:
            return text

        # 完整引用：整个值就是一个 ${...}
        m = _VAR_REF_RE.fullmatch(text)
        if m:
            try:
                entry = var_store.get(m.group(1))
                return entry["value"]
            except Exception:
                return text  # 变量不存在时保持原文本

        # 模板引用：逐个替换为字符串
        result = text
        for ref_path in refs:
            try:
                val = var_store.get_value(ref_path)
                if isinstance(val, (dict, list)):
                    import json
                    val = json.dumps(val, ensure_ascii=False)
                result = result.replace(f"${{{ref_path}}}", str(val))
            except Exception:
                pass  # 变量不存在时保持原文本
        return result

    # ── 结果变量 ────────────────────────────────────────────────────

    def _set_result_vars(self, command: str, args: dict[str, Any], result: dict):
        """命令成功后自动写入结果变量。"""
        from console.variable_store import store as var_store

        if not result.get("success"):
            return

        data = result.get("data", {})

        # 命令特定的结果变量
        if command == "build":
            frame = data.get("frame", "")
            if frame:
                try:
                    var_store.set("last_frame", frame, "hex", source={
                        "kind": "auto", "command": "build",
                    })
                except Exception:
                    pass
            try:
                var_store.set("last_build", data, "json", source={
                    "kind": "auto", "command": "build",
                })
            except Exception:
                pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "build",
                })
            except Exception:
                pass

        elif command == "decode":
            try:
                var_store.set("last_decode", data, "json", source={
                    "kind": "auto", "command": "decode",
                })
            except Exception:
                pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "decode",
                })
            except Exception:
                pass

        elif command == "find":
            try:
                var_store.set("last_find", data, "json", source={
                    "kind": "auto", "command": "find",
                })
            except Exception:
                pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "find",
                })
            except Exception:
                pass

        elif command == "split":
            try:
                var_store.set("last_split", data, "json", source={
                    "kind": "auto", "command": "split",
                })
            except Exception:
                pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "split",
                })
            except Exception:
                pass

        elif command == "serial":
            sub = str(args.get("sub") or "").lower()
            if sub == "send" or ("sent" in data and "sent_bytes" in data):
                try:
                    var_store.set("last_send", data, "json", source={
                        "kind": "auto", "command": "serial.send",
                    })
                except Exception:
                    pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": command,
                })
            except Exception:
                pass

        elif command == "wait-frame":
            try:
                update_last_rx({
                    "frame_hex": data.get("frame_hex"),
                    "decoded": data.get("decoded"),
                    "matched": data.get("matched"),
                    "elapsed_ms": data.get("elapsed_ms"),
                    "frame_index": data.get("frame_index"),
                }, command="wait-frame")
            except Exception:
                pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "wait-frame",
                })
            except Exception:
                pass

        elif command == "request":
            resp = data.get("response") if isinstance(data.get("response"), dict) else {}
            req = data.get("request") if isinstance(data.get("request"), dict) else {}
            try:
                update_last_rx({
                    "frame_hex": resp.get("frame_hex"),
                    "decoded": resp.get("decoded"),
                    "frame_index": resp.get("frame_index"),
                    "elapsed_ms": data.get("elapsed_ms"),
                }, command="request")
            except Exception:
                pass
            if req.get("frame_hex"):
                try:
                    var_store.set("last_send", {
                        "frame_hex": req.get("frame_hex"),
                        "decoded": req.get("decoded"),
                        "sent": req.get("frame_hex"),
                    }, "json", source={"kind": "auto", "command": "request"})
                except Exception:
                    pass
            try:
                var_store.set("last_result", data, "json", source={
                    "kind": "auto", "command": "request",
                })
            except Exception:
                pass

    def _set_error_result(self, command: str, error: str):
        """命令失败时写入 last_error。"""
        from console.variable_store import store as var_store

        try:
            var_store.set("last_error", {
                "command": command,
                "error": error,
            }, "json", source={"kind": "auto", "command": command})
        except Exception:
            pass

    # ── 映射 ──

    def _map_result(self, cmd: str, args: dict, result: dict) -> dict:
        """将业务模块 dict 映射到协议响应。"""
        if result.get("success"):
            data = result.get("data", {})
            # 检测是否需要继续交互 (如 build resolve 后需要补充参数)
            return response_success(data)

        error = result.get("error", "")
        detail = result.get("detail", {})

        # route_required → agent 必须先调 /route
        if result.get("status") == "route_required":
            return {
                "schema": "protocol-tui.v1",
                "status": "route_required",
                "error": error,
                "detail": detail,
                "path": result.get("path", ""),
            }

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
    parts = shlex.split(text.strip(), posix=False)
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
                value, i = merge_quoted_value_tail(value, parts, i)
                if key not in HEX_MERGE_KEYS:
                    value, i = merge_bracket_list_value_tail(value, parts, i)
                _add_arg(args, key, clean_string_arg(value, key=key))
            elif i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                key = raw
                value = parts[i + 1]
                i += 1
                if key in HEX_MERGE_KEYS:
                    value, i = merge_hex_value_tail(value, parts, i)
                else:
                    value, i = merge_bracket_list_value_tail(value, parts, i)
                _add_arg(args, key, clean_string_arg(value, key=key))
            else:
                _add_arg(args, raw, True)
        else:
            positional.append(token)
        i += 1
    if positional:
        args["_"] = positional
    return command, _normalize_args(args)


def _add_arg(args: dict[str, Any], key: str, value: Any) -> None:
    if key not in args:
        args[key] = value
        return
    existing = args[key]
    if isinstance(existing, list):
        existing.append(value)
    else:
        args[key] = [existing, value]


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "protocol": "proto",
        "direction": "dir",
    }
    normalized: dict[str, Any] = {}
    for key, value in args.items():
        normalized[aliases.get(key, key)] = value
    return normalized


def _consume_sub_command(command: str, args: dict[str, Any]) -> dict[str, Any]:
    """将位置参数中的子命令名移入 ``sub``，避免进入业务字段（如 build 的 ``_``）。"""
    cmd = registry.get(command)
    if not cmd or not cmd.sub_commands:
        return args
    out = dict(args)
    if out.get("sub"):
        return out
    pos = list(out.get("_") or [])
    if pos and str(pos[0]) in cmd.sub_commands:
        out["sub"] = str(pos.pop(0))
        if pos:
            out["_"] = pos
        else:
            out.pop("_", None)
    return out


# ── 全局单例 ──────────────────────────────────────────────────────────

def update_last_rx(payload: dict[str, Any], *, command: str = "serial.rx") -> None:
    """写入 last_rx 变量（串口 RX chunk 或 wait-frame/request 匹配帧）。"""
    from console.variable_store import store as var_store

    try:
        var_store.set("last_rx", payload, "json", source={
            "kind": "auto",
            "command": command,
        })
    except Exception:
        pass


runtime = Runtime()
