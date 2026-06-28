from __future__ import annotations

import re
from typing import Any

from test_runner.expressions import ExpressionError, resolve_fragment


_VAR_FRAGMENT_RE = re.compile(r"\$\{([^}]+)\}")


class VariableError(ValueError):
    pass


def resolve_value(value: Any, scope: dict[str, Any], *, soft: bool = False) -> Any:
    if isinstance(value, dict):
        return {k: resolve_value(v, scope, soft=soft) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, scope, soft=soft) for v in value]
    if not isinstance(value, str):
        return value

    whole = _VAR_FRAGMENT_RE.fullmatch(value)
    if whole:
        return _resolve_fragment_safe(whole.group(1), scope, soft=soft)

    def repl(match: re.Match[str]) -> str:
        try:
            resolved = _resolve_fragment_safe(match.group(1), scope, soft=soft)
        except VariableError:
            if soft:
                return match.group(0)
            raise
        if isinstance(resolved, (dict, list)):
            raise VariableError(f"cannot interpolate non-scalar variable: {match.group(1)}")
        return "" if resolved is None else str(resolved)

    return _VAR_FRAGMENT_RE.sub(repl, value)


def _resolve_fragment_safe(inner: str, scope: dict[str, Any], *, soft: bool = False) -> Any:
    try:
        return resolve_fragment(inner, scope)
    except ExpressionError as exc:
        raise VariableError(str(exc)) from exc
    except VariableError:
        if soft:
            return "${" + inner + "}"
        raise


def _tokenize_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    buf = ""
    i = 0

    def flush_buf() -> None:
        nonlocal buf
        if not buf:
            return
        tokens.append(int(buf) if buf.isdigit() else buf)
        buf = ""

    while i < len(path):
        char = path[i]
        if char == ".":
            flush_buf()
            i += 1
            continue
        if char == "[":
            flush_buf()
            close = path.index("]", i)
            tokens.append(int(path[i + 1:close]))
            i = close + 1
            continue
        buf += char
        i += 1
    flush_buf()
    return tokens


def _access_index(current: list[Any], index: int, path: str) -> Any:
    if index < 0 or index >= len(current):
        raise VariableError(f"unknown variable: {path}")
    return current[index]


def get_path(scope: dict[str, Any], path: str) -> Any:
    parts = _tokenize_path(path)
    if not parts:
        raise VariableError(f"unknown variable: {path}")

    current: Any = scope
    i = 0
    while i < len(parts):
        part = parts[i]
        if isinstance(part, int):
            if not isinstance(current, list):
                raise VariableError(f"unknown variable: {path}")
            current = _access_index(current, part, path)
            i += 1
            continue

        if isinstance(current, list):
            if str(part).isdigit():
                current = _access_index(current, int(part), path)
                i += 1
                continue
            raise VariableError(f"unknown variable: {path}")

        if isinstance(current, dict):
            found = False
            for j in range(len(parts), i, -1):
                key = ".".join(str(p) for p in parts[i:j])
                if key in current:
                    current = current[key]
                    i = j
                    found = True
                    break
            if not found:
                raise VariableError(f"unknown variable: {path}")
            continue

        raise VariableError(f"unknown variable: {path}")
    return current
