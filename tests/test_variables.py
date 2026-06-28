from __future__ import annotations

import pytest

from test_runner.variables import VariableError, get_path, resolve_value


SCOPE = {
    "conn": "cco",
    "batches": [
        {"start_index": 0, "addrs": ["01 00 00 00 00 00", "02 00 00 00 00 00"]},
        {"start_index": 32, "addrs": ["21 00 00 00 00 00"]},
    ],
    "device": {"port": "mock://auto", "baudrate": 9600},
    "nested": {"user_data.slave_total": 1024},
}


def test_get_path_struct():
    assert get_path(SCOPE, "device.port") == "mock://auto"
    assert get_path(SCOPE, "device.baudrate") == 9600


def test_get_path_array_dot_index():
    assert get_path(SCOPE, "batches.0.start_index") == 0
    assert get_path(SCOPE, "batches.1.addrs.0") == "21 00 00 00 00 00"


def test_get_path_array_bracket_index():
    assert get_path(SCOPE, "batches[0].start_index") == 0
    assert get_path(SCOPE, "batches[1].addrs[0]") == "21 00 00 00 00 00"


def test_get_path_dotted_dict_key():
    assert get_path(SCOPE, "nested.user_data.slave_total") == 1024


def test_resolve_whole_object():
    batch = resolve_value("${batches.0}", SCOPE)
    assert batch["start_index"] == 0
    assert len(batch["addrs"]) == 2


def test_resolve_scalar_interpolation():
    assert resolve_value("port=${device.port}", SCOPE) == "port=mock://auto"


def test_resolve_rejects_non_scalar_interpolation():
    with pytest.raises(VariableError):
        resolve_value("x=${batches.0}", SCOPE)


def test_get_path_out_of_range():
    with pytest.raises(VariableError):
        get_path(SCOPE, "batches.9.start_index")
