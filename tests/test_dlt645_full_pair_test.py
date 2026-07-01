"""DLT645 配对全量 build/decode pytest 封装。"""

from __future__ import annotations

import pytest

from protocol_tool.ir.nodes import ProtocolIR
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

from tests.dlt645_pair_catalog import (
    format_pair_chain,
    iter_pair_messages,
    load_dlt645_pairs,
    validate_downlink_coverage,
)
from tests.protocol_build_utils import run_dlt645_pair_message
from tests.protocol_info import DLT645_FIELD_DEFAULTS

_COMPILED = "compiled/dlt645_2007.ir.json"


@pytest.fixture(scope="module")
def dlt645_pair_engines():
    ir = ProtocolIR.from_json_file(_COMPILED)
    codecs = create_builtin_registry()
    return ir, BuildEngine(ir, codecs), DecodeEngine(ir, codecs)


@pytest.fixture(scope="module")
def dlt645_pairs_data():
    data = load_dlt645_pairs()
    missing = validate_downlink_coverage(data)
    assert not missing, f"missing downlink in pairs yaml: {missing}"
    return data


def _iter_param_cases(pairs_data):
    for pair in pairs_data["pairs"]:
        for msg in iter_pair_messages(pair):
            yield pytest.param(
                pair["id"],
                msg.slot,
                msg,
                id=f"{pair['id']}:{msg.slot}",
            )


@pytest.mark.parametrize("pair_id,slot,msg", list(_iter_param_cases(load_dlt645_pairs())))
def test_dlt645_pair_message_build_decode(pair_id, slot, msg, dlt645_pair_engines):
    ir, build_engine, decode_engine = dlt645_pair_engines
    result = run_dlt645_pair_message(
        msg, ir, build_engine, decode_engine, DLT645_FIELD_DEFAULTS,
    )
    assert result.status == "PASS", (
        f"{pair_id}/{slot} FUNC={msg.func} DI={msg.di or '-'}: {result.error}"
    )


def test_dlt645_pairs_cover_downlink_map(dlt645_pairs_data):
    assert validate_downlink_coverage(dlt645_pairs_data) == []


def test_format_pair_chain_read_data():
    data = load_dlt645_pairs()
    pair = next(p for p in data["pairs"] if p["id"] == "read_data_0001ff00")
    chain = format_pair_chain(pair)
    assert chain == "func11/0001ff00 ---> [func11/0001ff00]"
