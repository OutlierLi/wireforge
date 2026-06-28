from __future__ import annotations

import pytest

from test_runner.expressions import eval_expression
from test_runner.variables import VariableError, resolve_value


def test_eval_expression_basic():
    assert eval_expression("1 + 2 * 3", {}) == 7
    assert eval_expression("qi * 32 + 1", {"qi": 2}) == 65


def test_resolve_expression_whole():
    assert resolve_value("${i * 32}", {"i": 3}) == 96
    assert resolve_value("${qi * 32 + start}", {"qi": 2, "start": 1}) == 65


def test_resolve_path_still_works():
    scope = {"device": {"port": "mock://auto"}, "batches": [{"start_index": 0}]}
    assert resolve_value("${device.port}", scope) == "mock://auto"
    assert resolve_value("${batches.0.start_index}", scope) == 0


def test_expr_rejects_unknown_variable():
    with pytest.raises(VariableError):
        resolve_value("${missing + 1}", {})


def test_expr_rejects_non_numeric_variable():
    with pytest.raises(VariableError):
        resolve_value("${device.port + 1}", {"device": {"port": "mock://auto"}})
