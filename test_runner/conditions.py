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
