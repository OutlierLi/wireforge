from __future__ import annotations

import ast
import operator
from typing import Any

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


_EXPR_CHARS = set("+-*/%()")


class ExpressionError(ValueError):
    pass


def looks_like_expression(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if any(ch in _EXPR_CHARS for ch in stripped):
        return True
    if " " in stripped and not stripped.replace(" ", "").replace(".", "").replace("[", "").replace("]", "").isalnum():
        return True
    return False


def resolve_fragment(inner: str, scope: dict[str, Any]) -> Any:
    from test_runner.variables import VariableError, get_path

    text = inner.strip()
    if not text:
        raise ExpressionError("empty variable reference")

    if looks_like_expression(text):
        return eval_expression(text, scope)

    try:
        return get_path(scope, text)
    except VariableError:
        if looks_like_expression(text):
            return eval_expression(text, scope)
        raise


def eval_expression(expr: str, scope: dict[str, Any]) -> Any:
    try:
        tree = ast.parse(str(expr).strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression: {expr}") from exc
    return _eval_node(tree.body, scope)


def _eval_node(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ExpressionError(f"unsupported literal: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise ExpressionError(f"unknown variable in expression: {node.id}")
        value = scope[node.id]
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        raise ExpressionError(f"non-numeric variable in expression: {node.id}")

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("unsupported unary operator")
        return op(_eval_node(node.operand, scope))

    if isinstance(node, ast.BinOp):
        op = _BINARY_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("unsupported binary operator")
        left = _eval_node(node.left, scope)
        right = _eval_node(node.right, scope)
        return op(left, right)

    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")
