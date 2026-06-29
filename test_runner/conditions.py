from __future__ import annotations

from typing import Any

from test_runner.variables import resolve_value


def values_equal(actual: Any, expected: Any) -> bool:
    return str(actual) == str(expected)


def evaluate_expect(conditions: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Assert-style expect: {path: expected, ...}"""
    for path, expected in conditions.items():
        if path in {"op"}:
            continue
        try:
            actual = resolve_value("${" + path + "}", scope)
        except Exception:
            actual = None
        if not values_equal(actual, expected):
            return False
    return True


def evaluate_when(when: Any, scope: dict[str, Any]) -> bool:
    if when is None:
        return True
    if isinstance(when, str):
        return _evaluate_when_string(when.strip(), scope)
    if not isinstance(when, dict):
        return bool(when)

    if "all" in when:
        items = when["all"]
        if not isinstance(items, list):
            raise ValueError("when.all must be a list")
        return all(evaluate_when(item, scope) for item in items)

    if "not" in when:
        return not evaluate_when(when["not"], scope)

    if "eq" in when:
        eq = when["eq"]
        if not isinstance(eq, dict):
            raise ValueError("when.eq must be an object")
        return evaluate_expect(eq, scope)

    # bare expect map
    return evaluate_expect(when, scope)


def _evaluate_when_string(expr: str, scope: dict[str, Any]) -> bool:
    """Simple string conditions: port == mock://auto, port != COM3, not flag."""
    if not expr:
        return True
    if expr.startswith("not "):
        return not _evaluate_when_string(expr[4:].strip(), scope)
    for op in ("==", "!="):
        if op not in expr:
            continue
        left, right = expr.split(op, 1)
        left_val = _resolve_when_operand(left.strip(), scope)
        right_val = _resolve_when_operand(right.strip(), scope)
        if op == "==":
            return values_equal(left_val, right_val)
        return not values_equal(left_val, right_val)
    # bare path truthiness
    try:
        val = resolve_value("${" + expr + "}", scope)
    except Exception:
        return False
    return bool(val)


def _resolve_when_operand(token: str, scope: dict[str, Any]) -> Any:
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        return token[1:-1]
    if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
        return int(token)
    try:
        return resolve_value("${" + token + "}", scope)
    except Exception:
        return token
