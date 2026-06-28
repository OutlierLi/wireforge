from __future__ import annotations

import re
from typing import Any


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}")


class VariableError(ValueError):
    pass


def resolve_value(value: Any, scope: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: resolve_value(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, scope) for v in value]
    if not isinstance(value, str):
        return value

    whole = _VAR_RE.fullmatch(value)
    if whole:
        return get_path(scope, whole.group(1))

    def repl(match: re.Match[str]) -> str:
        resolved = get_path(scope, match.group(1))
        if isinstance(resolved, (dict, list)):
            raise VariableError(f"cannot interpolate non-scalar variable: {match.group(1)}")
        return "" if resolved is None else str(resolved)

    return _VAR_RE.sub(repl, value)


def get_path(scope: dict[str, Any], path: str) -> Any:
    current: Any = scope
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise VariableError(f"unknown variable: {path}")
    return current

