"""命令树顺序补全 — 按 command → sub → params 层级联想。

规则：
- 同级候选一起返回，按 required → recommended → optional 排序
- sub_command 互斥：选定后不再联想其它 sub
- 非 repeatable 参数一旦赋值后不再联想
- repeatable 参数（如 filter、var）每次都可联想
- 参数赋值阶段（``--port `` / ``--port=`` / ``--port mo``）联想 default + examples
- ``--then`` 等脚本参数内嵌 ``/command`` 时，按嵌套命令继续联想（如 ``/print --text``）
- ``/help`` 的 ``target`` 为嵌套命令路径（``--target /serial connect`` 或 ``/help /serial``）逐级联想
- ``/build`` / ``/route`` 在 ``--proto`` 之后按路由键 → protocol_map 全量取值 → resolve schema 动态联想
- 输入 --prefix 时跨层级前缀匹配
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any

from console.command import registry
from console.command_schema import (
    DEFAULT_SUB,
    effective_params,
    param_sort_key,
    param_value_candidates,
    sorted_params,
    sub_command_desc,
)
from console.protocol import response_success
from console.build_completion import (
    build_argument_completions,
    build_argument_value_completions,
    route_argument_completions,
    route_argument_value_completions,
    schema_field_meta,
)

# 终端内置命令（不在 commands.json，由 terminal 直接处理）
_BUILTIN_TERMINAL_COMMANDS: tuple[tuple[str, str], ...] = (
    ("exit", "退出交互终端"),
    ("quit", "退出交互终端（同 /exit）"),
)


@dataclass
class CompletionState:
    text: str
    complete_tokens: list[str] = field(default_factory=list)
    current_token: str = ""
    ends_with_space: bool = False
    stage: str = "command"  # command | sub_command | argument | argument_value
    command: str = ""
    sub: str = ""
    sub_locked: bool = False
    used_args: dict[str, Any] = field(default_factory=dict)
    flag_prefix: str = ""
    value_param: str = ""
    value_prefix: str = ""
    nested: CompletionState | None = None


_NESTED_SCRIPT_PARAMS = frozenset({"then"})
_NESTED_COMMAND_TARGET_COMMANDS = frozenset({"help"})
_OUTER_AUTO_RULE_FLAGS = frozenset({
    "--id", "--match", "--name", "--source", "--field", "--di", "--afn", "--dir",
    "--cooldown", "--mode", "--on_error", "--event", "--pattern", "--match_type",
    "--condition_type", "--enabled", "--sub", "--actions",
})


def param_is_repeatable(meta: dict[str, Any]) -> bool:
    if meta.get("repeatable"):
        return True
    blob = f"{meta.get('desc', '')} {meta.get('note', '')}"
    return "可多次" in blob or "may be repeated" in blob.lower()


def param_is_used(key: str, used_args: dict[str, Any], meta: dict[str, Any]) -> bool:
    if param_is_repeatable(meta):
        return False
    if key not in used_args:
        return False
    val = used_args[key]
    if val is True:
        return True
    if val is None or val == "":
        return False
    return True


def _close_dangling_quotes(text: str) -> str:
    for quote in ('"', "'"):
        if text.count(quote) % 2 == 1:
            text = text + quote
    return text


def _safe_shlex_split(text: str) -> list[str]:
    """补全场景下容错分词 — 未闭合引号不抛异常。"""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return shlex.split(stripped, posix=False)
    except ValueError:
        try:
            return shlex.split(_close_dangling_quotes(stripped), posix=False)
        except ValueError:
            return stripped.split()


def tokenize_for_completion(text: str) -> tuple[list[str], str, bool]:
    ends_with_space = bool(text) and text[-1] in " \t"
    stripped = text.strip()
    if not stripped:
        return [], "", ends_with_space

    if ends_with_space:
        return _safe_shlex_split(stripped), "", True

    head = text.rstrip()
    last_space = head.rfind(" ")
    if last_space < 0:
        return [], head.lstrip(), False

    prefix_text = head[:last_space]
    partial = head[last_space + 1 :]
    complete = _safe_shlex_split(prefix_text) if prefix_text.strip() else []
    return complete, partial, False


def _parse_used_args(tokens: list[str], start: int) -> dict[str, Any]:
    args: dict[str, Any] = {}
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            raw = token[2:]
            if "=" in raw:
                key, value = raw.split("=", 1)
                _merge_arg(args, key, value)
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                _merge_arg(args, raw, tokens[i + 1])
                i += 1
            else:
                _merge_arg(args, raw, True)
        i += 1
    return args


def _parse_used_args_for_completion(
    tokens: list[str],
    start: int,
    *,
    ends_with_space: bool = False,
    current_token: str = "",
) -> dict[str, Any]:
    """补全用：``--di `` / ``--di E8`` 等待赋值时不把 flag 记成 True。"""
    args = _parse_used_args(tokens, start)
    if not tokens:
        return args
    last = tokens[-1]
    if not last.startswith("--") or "=" in last:
        return args
    key = last[2:]
    if args.get(key) is not True:
        return args
    if ends_with_space:
        del args[key]
        return args
    if current_token and not current_token.startswith("--"):
        del args[key]
    return args


def _merge_arg(args: dict[str, Any], key: str, value: Any = True) -> None:
    if key not in args:
        args[key] = value
        return
    existing = args[key]
    if isinstance(existing, list):
        existing.append(value)
    else:
        args[key] = [existing, value]


def _resolve_build_sub(used_args: dict[str, Any]) -> str:
    if used_args.get("from_frame") or used_args.get("from-frame"):
        return "from-frame"
    if used_args.get("resolve") or used_args.get("describe") or used_args.get("schema"):
        return "resolve"
    return ""


def _implicit_sub(command: str, tokens: list[str]) -> str:
    if command == "build":
        build_sub = _resolve_build_sub(_parse_used_args(tokens, 1))
        if build_sub:
            return build_sub
    return DEFAULT_SUB.get(command, "")


def _param_expects_value(meta: dict[str, Any]) -> bool:
    if meta.get("type") == "bool":
        return False
    if meta.get("positional"):
        return True
    if param_value_candidates(meta):
        return True
    return meta.get("type", "str") in ("str", "int", "choice", "float", "dynamic")


def _resolve_value_completion(state: CompletionState) -> bool:
    """识别参数赋值阶段，设置 value_param / value_prefix。"""
    tokens = state.complete_tokens
    partial = state.current_token
    cmd = registry.get(state.command)
    sub = state.sub or DEFAULT_SUB.get(state.command, "")
    if not cmd or not sub:
        return False

    def _meta_for(key: str) -> dict[str, Any] | None:
        meta = effective_params(cmd, sub).get(key)
        if isinstance(meta, dict):
            return meta
        if state.command == "build":
            from console.build_completion import schema_field_meta as _schema_meta
            return _schema_meta(state.used_args, key)
        if state.command == "route":
            return schema_field_meta(state.used_args, key)
        return None

    # 正在输入新 flag（非 --key=partial 形式）→ 不是值补全
    if partial.startswith("--") and "=" not in partial:
        return False

    # `--port `：flag 后空格，尚未给值
    if state.ends_with_space and tokens:
        last = tokens[-1]
        if last.startswith("--") and "=" not in last:
            meta = _meta_for(last[2:])
            if meta and _param_expects_value(meta):
                state.value_param = last[2:]
                state.value_prefix = ""
                state.stage = "argument_value"
                return True
        return False

    # `--port=partial` 在当前 partial 或最后一个 token
    equals_sources: list[str] = []
    if partial.startswith("--") and "=" in partial:
        equals_sources.append(partial)
    elif not partial and tokens:
        equals_sources.append(tokens[-1])

    for token in equals_sources:
        if token.startswith("--") and "=" in token:
            key, val = token[2:].split("=", 1)
            meta = _meta_for(key)
            if meta and _param_expects_value(meta):
                state.value_param = key
                state.value_prefix = val
                state.stage = "argument_value"
                return True

    # `--port mo`：空格分隔的值
    if tokens and tokens[-1].startswith("--") and "=" not in tokens[-1]:
        if partial and not partial.startswith("--"):
            meta = _meta_for(tokens[-1][2:])
            if meta and _param_expects_value(meta):
                state.value_param = tokens[-1][2:]
                state.value_prefix = partial
                state.stage = "argument_value"
                return True

    return False


def analyze_completion_line(text: str) -> CompletionState:
    state = _analyze_completion_line_impl(text)
    _maybe_attach_nested_script(state)
    _maybe_attach_nested_command_target(state)
    return state


def _then_is_active(tokens: list[str], partial: str) -> bool:
    if any(t == "--then" or t.startswith("--then=") for t in tokens):
        return True
    return partial.startswith("/") and "--then" in tokens


def _extract_nested_script_tail(
    tokens: list[str],
    partial: str,
    ends_with_space: bool,
) -> str | None:
    then_idx: int | None = None
    inline_value = ""
    for i, t in enumerate(tokens):
        if t == "--then":
            then_idx = i
            break
        if t.startswith("--then="):
            then_idx = i
            inline_value = t.split("=", 1)[1]
            break

    if then_idx is None:
        if partial.startswith("/"):
            return (partial + " ") if ends_with_space else partial
        return None

    parts: list[str] = []
    if inline_value:
        parts.append(inline_value)
    for t in tokens[then_idx + 1:]:
        base = t.split("=", 1)[0]
        if base in _OUTER_AUTO_RULE_FLAGS:
            break
        parts.append(t)

    tail = " ".join(parts).strip()
    if partial and partial not in tokens:
        if partial.startswith(("/", "--")) or tail:
            if not tail.endswith(partial):
                tail = f"{tail} {partial}".strip() if tail else partial

    if not tail and not ends_with_space:
        return None
    if ends_with_space:
        return (tail + " ") if tail else " "
    return tail or None


def _maybe_attach_nested_script(state: CompletionState) -> None:
    if state.command != "auto_rule" or state.sub not in ("add", "update") or not state.sub_locked:
        return
    if not _then_is_active(state.complete_tokens, state.current_token):
        return
    tail = _extract_nested_script_tail(
        state.complete_tokens,
        state.current_token,
        state.ends_with_space,
    )
    if tail is None:
        return
    state.nested = _analyze_completion_line_impl(tail)
    state.stage = "nested_script"


def _normalize_help_target_tail(tail: str, *, ends_with_space: bool) -> str:
    text = tail.strip()
    if not text:
        return "/ " if ends_with_space else "/"
    if not text.startswith("/"):
        text = f"/{text.lstrip('/')}"
    if ends_with_space and not text.endswith(" "):
        text += " "
    return text


def _collect_help_target_parts(
    complete_tokens: list[str],
    current_token: str,
) -> list[str]:
    """收集 help target 路径 token（含 --target 后的多词路径）。"""
    parts: list[str] = []
    i = 1
    while i < len(complete_tokens):
        t = complete_tokens[i]
        if t == "--target":
            i += 1
            while i < len(complete_tokens) and not complete_tokens[i].startswith("--"):
                parts.append(complete_tokens[i])
                i += 1
            continue
        if t.startswith("--target="):
            parts.append(t.split("=", 1)[1])
            i += 1
            continue
        if t.startswith("--"):
            i += 1
            continue
        parts.append(t)
        i += 1
    if current_token and not current_token.startswith("--") and current_token not in complete_tokens:
        parts.append(current_token)
    return parts


def _extract_help_target_tail(
    complete_tokens: list[str],
    current_token: str,
    ends_with_space: bool,
) -> str | None:
    if not complete_tokens or complete_tokens[0].lstrip("/") != "help":
        return None

    parts = _collect_help_target_parts(complete_tokens, current_token)
    if parts and parts[0].startswith("/"):
        return _normalize_help_target_tail(" ".join(parts), ends_with_space=ends_with_space)

    used = _parse_used_args(complete_tokens, 1)
    target_val = used.get("target")
    if target_val is True:
        if current_token and not current_token.startswith("--"):
            return _normalize_help_target_tail(current_token, ends_with_space=ends_with_space)
        if ends_with_space:
            return "/ "
        return None

    if isinstance(target_val, str) and target_val.strip():
        tail = target_val.strip()
        if current_token and not current_token.startswith("--") and current_token not in complete_tokens:
            if current_token.startswith("/"):
                tail = current_token
            else:
                tail = f"{tail} {current_token}".strip()
        return _normalize_help_target_tail(tail, ends_with_space=ends_with_space)

    if current_token.startswith("--target="):
        val = current_token.split("=", 1)[1]
        return _normalize_help_target_tail(val, ends_with_space=ends_with_space)

    if len(complete_tokens) == 1 and ends_with_space:
        return "/ "

    return None


def _maybe_attach_nested_command_target(state: CompletionState) -> None:
    if state.command not in _NESTED_COMMAND_TARGET_COMMANDS:
        return
    tail = _extract_help_target_tail(
        state.complete_tokens,
        state.current_token,
        state.ends_with_space,
    )
    if tail is None:
        if (
            state.stage == "argument_value"
            and state.value_param == "target"
            and (not state.value_prefix or state.value_prefix.startswith("/"))
        ):
            tail = _normalize_help_target_tail(
                state.value_prefix or "",
                ends_with_space=state.ends_with_space,
            )
        else:
            return
    state.sub = DEFAULT_SUB.get(state.command, state.sub or "")
    state.sub_locked = True
    state.nested = _analyze_completion_line_impl(tail)
    state.stage = "nested_target"


def _analyze_completion_line_impl(text: str) -> CompletionState:
    complete_tokens, current_token, ends_with_space = tokenize_for_completion(text)
    state = CompletionState(
        text=text,
        complete_tokens=complete_tokens,
        current_token=current_token,
        ends_with_space=ends_with_space,
    )

    if not complete_tokens and not current_token:
        state.stage = "command"
        return state

    if not complete_tokens:
        state.stage = "command"
        state.command = current_token.lstrip("/")
        return state

    command = complete_tokens[0].lstrip("/")
    state.command = command
    cmd = registry.get(command)
    if cmd is None:
        state.stage = "command"
        return state

    if len(complete_tokens) == 1 and ends_with_space:
        default_sub = DEFAULT_SUB.get(command, "")
        if (
            default_sub
            and default_sub in cmd.sub_commands
            and len(cmd.sub_commands) == 1
        ):
            state.sub = default_sub
            state.sub_locked = True
            state.stage = "argument"
            return state
        state.stage = "sub_command"
        return state

    if len(complete_tokens) == 1 and current_token:
        if command == "help" and current_token.startswith("/"):
            state.sub = DEFAULT_SUB.get(command, "")
            state.sub_locked = True
            state.stage = "argument"
            return state
        if current_token.startswith("--"):
            implicit = _implicit_sub(command, [current_token])
            if implicit:
                state.sub = implicit
                state.sub_locked = True
                state.used_args = _parse_used_args([current_token], 0)
                state.stage = "argument"
                state.flag_prefix = current_token
                return state
            state.stage = "sub_command"
            return state
        if current_token in cmd.sub_commands:
            state.sub = current_token
            state.sub_locked = True
            state.stage = "argument"
            return state
        state.stage = "sub_command"
        return state

    second = complete_tokens[1]
    arg_start = 2

    if second in cmd.sub_commands:
        state.sub = second
        state.sub_locked = True
        state.used_args = _parse_used_args_for_completion(
            complete_tokens, arg_start,
            ends_with_space=ends_with_space,
            current_token=current_token,
        )
    elif second.startswith("--"):
        implicit = _implicit_sub(command, complete_tokens[1:])
        if implicit:
            state.sub = implicit
            state.sub_locked = True
            arg_start = 1
            state.used_args = _parse_used_args_for_completion(
                complete_tokens, arg_start,
                ends_with_space=ends_with_space,
                current_token=current_token,
            )
        else:
            state.stage = "sub_command"
            return state
    else:
        if command == "help" and second.startswith("/"):
            state.sub = DEFAULT_SUB.get(command, "")
            state.sub_locked = True
            state.stage = "argument"
            return state
        state.stage = "sub_command"
        if not current_token:
            state.current_token = second
        return state

    if current_token.startswith("--"):
        if _resolve_value_completion(state):
            return state
        state.stage = "argument"
        state.flag_prefix = current_token
        return state

    if current_token and current_token == state.sub:
        state.stage = "argument"
        return state

    if ends_with_space:
        if _resolve_value_completion(state):
            return state
        state.stage = "argument"
        return state

    if not current_token and state.sub_locked:
        if _resolve_value_completion(state):
            return state
        state.stage = "argument"
        return state

    if current_token and not current_token.startswith("--") and complete_tokens and complete_tokens[-1].startswith("--"):
        if _resolve_value_completion(state):
            return state

    state.stage = "argument"
    return state


def completion_start_position(state: CompletionState) -> int:
    if state.stage == "argument_value":
        if state.value_prefix:
            return -len(state.value_prefix)
        return 0
    if state.ends_with_space:
        return 0
    if state.stage in ("argument", "argument_value") and state.sub_locked and not state.current_token:
        return 0
    if state.stage == "argument" and state.sub_locked and state.current_token == state.sub:
        return 0
    if not state.current_token:
        return 0
    return -len(state.current_token)


def _flag_matches(flag: str, prefix: str) -> bool:
    if not prefix:
        return True
    if prefix.startswith("--"):
        return flag.startswith(prefix) or flag[2:].startswith(prefix[2:])
    return flag[2:].startswith(prefix.lstrip("-"))


def _argument_completions(
    cmd_name: str,
    sub: str,
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]]:
    cmd = registry.get(cmd_name)
    if not cmd or not sub:
        return []

    params = effective_params(cmd, sub)
    typing_flag = bool(flag_prefix)

    tier: dict[int, list[tuple[str, dict[str, Any]]]] = {0: [], 1: [], 2: []}
    prefix_matches: list[tuple[str, dict[str, Any]]] = []

    for key, meta in sorted_params(params):
        flag = f"--{key}"
        if typing_flag and not _flag_matches(flag, flag_prefix):
            continue

        if param_is_repeatable(meta):
            if typing_flag:
                prefix_matches.append((key, meta))
            else:
                tier[2].append((key, meta))
            continue

        if param_is_used(key, used_args, meta):
            continue

        rank = param_sort_key(key, meta)[0]
        if typing_flag:
            prefix_matches.append((key, meta))
        else:
            tier[rank].append((key, meta))

    if typing_flag:
        selected = prefix_matches
    else:
        selected = []
        for rank in (0, 1, 2):
            if tier[rank]:
                selected = tier[rank]
                break
        selected = list(selected)

    completions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, meta in selected:
        if key in seen:
            continue
        seen.add(key)
        flag = key if meta.get("positional") else f"--{key}"
        item: dict[str, Any] = {
            "kind": "argument",
            "value": flag,
            "label": flag,
            "type": meta.get("type", "str"),
            "required": bool(meta.get("required", False)),
            "description": meta.get("desc", ""),
        }
        if meta.get("recommended"):
            item["recommended"] = True
        if param_is_repeatable(meta):
            item["repeatable"] = True
        if "examples" in meta:
            item["examples"] = meta["examples"]
        if "default" in meta:
            item["default"] = meta["default"]
        completions.append(item)
    return completions


def _value_prefix_matches(candidate: str, prefix: str) -> bool:
    if not prefix:
        return True
    return candidate.lower().startswith(prefix.lower())


def _argument_value_completions(
    cmd_name: str,
    sub: str,
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]]:
    cmd = registry.get(cmd_name)
    if not cmd or not sub or not param_key:
        return []

    meta = effective_params(cmd, sub).get(param_key)
    if not isinstance(meta, dict):
        return []

    default_text = meta.get("default")
    completions: list[dict[str, Any]] = []
    for val in param_value_candidates(meta):
        if not _value_prefix_matches(val, value_prefix):
            continue
        label = val
        is_default = default_text is not None and str(default_text) == val
        if is_default:
            label = f"{val} (default)"
        item: dict[str, Any] = {
            "kind": "argument_value",
            "value": val,
            "label": label,
            "param": param_key,
        }
        if is_default:
            item["default"] = True
        completions.append(item)
    return completions


def _completions_for_state(state: CompletionState) -> list[dict[str, Any]]:
    completions: list[dict[str, Any]] = []

    if state.stage == "command":
        raw = state.current_token.lstrip("/") if state.current_token else ""
        if state.complete_tokens and not state.current_token:
            raw = state.complete_tokens[0].lstrip("/")
        seen: set[str] = set()
        for name in registry.names():
            if not raw or name.startswith(raw):
                seen.add(name)
                completions.append({
                    "kind": "command",
                    "value": f"/{name}",
                    "label": f"/{name}",
                })
        for name, desc in _BUILTIN_TERMINAL_COMMANDS:
            if name in seen:
                continue
            if not raw or name.startswith(raw):
                completions.append({
                    "kind": "command",
                    "value": f"/{name}",
                    "label": f"/{name}",
                    "description": desc,
                })
        completions.sort(key=lambda item: item["value"])
        return completions

    cmd = registry.get(state.command)
    if not cmd:
        return completions

    if state.stage == "sub_command" and not state.sub_locked:
        raw = state.current_token
        if state.complete_tokens and len(state.complete_tokens) >= 2 and not raw:
            raw = state.complete_tokens[1]
        for sub_name in cmd.sub_commands:
            if not raw or sub_name.startswith(raw):
                completions.append({
                    "kind": "sub_command",
                    "value": sub_name,
                    "label": sub_name,
                    "description": sub_command_desc(cmd, sub_name),
                })
        return completions

    sub = state.sub or DEFAULT_SUB.get(state.command, "")
    if state.stage == "argument_value" and state.value_param:
        if state.command == "build":
            dynamic = build_argument_value_completions(
                state.used_args, state.value_param, state.value_prefix,
            )
            if dynamic is not None:
                return dynamic
        elif state.command == "route":
            dynamic = route_argument_value_completions(
                state.used_args, state.value_param, state.value_prefix,
            )
            if dynamic is not None:
                return dynamic
        return _argument_value_completions(
            state.command,
            sub,
            state.value_param,
            state.value_prefix,
        )
    if state.stage == "argument":
        if state.command == "build":
            dynamic = build_argument_completions(state.used_args, state.flag_prefix)
            if dynamic is not None:
                return dynamic
        elif state.command == "route":
            dynamic = route_argument_completions(state.used_args, state.flag_prefix)
            if dynamic is not None:
                return dynamic
        return _argument_completions(
            state.command,
            sub,
            state.used_args,
            state.flag_prefix,
        )
    return completions


def complete_text(text: str) -> dict[str, Any]:
    try:
        return _complete_text_impl(text)
    except Exception:
        return response_success({
            "completions": [],
            "stage": "command",
            "start_position": 0,
        })


def _complete_text_impl(text: str) -> dict[str, Any]:
    state = analyze_completion_line(text)
    active = state.nested if state.stage.startswith("nested_") and state.nested else state
    completions = _completions_for_state(active)
    return response_success({
        "completions": completions,
        "stage": state.stage,
        "start_position": completion_start_position(active),
    })


def complete_legacy(prefix: str = "", command: str = "", sub: str = "") -> dict[str, Any]:
    """兼容 command/sub/prefix 分离的旧 API。"""
    command = command.lstrip("/")
    if not command:
        return complete_text(prefix or "")

    parts = [f"/{command}"]
    if sub:
        parts.append(sub)
    if prefix:
        parts.append(prefix)
    text = " ".join(parts)
    if sub and not prefix:
        text = f"{text} "
    elif not sub and not prefix:
        text = f"/{command} "
    return complete_text(text)
