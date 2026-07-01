"""CSG 配对全量 build/decode pytest 封装。"""

from __future__ import annotations

import pytest

from protocol_tool.ir.nodes import ProtocolIR
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

from tests.csg_pair_catalog import (
    format_pair_di_chain,
    iter_pair_messages,
    iter_pair_scenarios,
    load_csg_pairs,
    validate_table4_coverage,
)
from tests.protocol_build_utils import run_pair_message
from tests.protocol_info import CSG_FIELD_DEFAULTS

_COMPILED = "compiled/csg_2016.ir.json"


@pytest.fixture(scope="module")
def csg_pair_engines():
    ir = ProtocolIR.from_json_file(_COMPILED)
    codecs = create_builtin_registry()
    return ir, BuildEngine(ir, codecs), DecodeEngine(ir, codecs)


@pytest.fixture(scope="module")
def csg_pairs_data():
    data = load_csg_pairs()
    missing = validate_table4_coverage(data)
    assert not missing, f"missing table4 downlink in pairs yaml: {missing}"
    return data


def _iter_param_cases(pairs_data):
    for pair in pairs_data["pairs"]:
        for msg in iter_pair_messages(pair):
            yield pytest.param(
                pair["id"],
                msg.scenario_id,
                msg.slot,
                msg,
                id=f"{pair['id']}:{msg.scenario_id}:{msg.slot}",
            )


@pytest.mark.parametrize("pair_id,scenario_id,slot,msg", list(_iter_param_cases(load_csg_pairs())))
def test_csg_pair_message_build_decode(pair_id, scenario_id, slot, msg, csg_pair_engines):
    ir, build_engine, decode_engine = csg_pair_engines
    result = run_pair_message(msg, ir, build_engine, decode_engine, CSG_FIELD_DEFAULTS)
    assert result.status == "PASS", (
        f"{pair_id}/{scenario_id}/{slot} AFN={msg.afn} DI={msg.di}: {result.error}"
    )


def test_csg_pairs_cover_pdf_table4(csg_pairs_data):
    assert validate_table4_coverage(csg_pairs_data) == []


def test_format_pair_di_chain_add_task():
    data = load_csg_pairs()
    pair = next(p for p in data["pairs"] if p["id"] == "afn02_add_task")
    assert [item["id"] for item in iter_pair_scenarios(pair)] == ["success", "nak"]
    assert format_pair_di_chain(pair, "success") == (
        "e8020201 ---> [e8010001, e8050501, e8050501, e8050501, e8050505]"
    )
    assert format_pair_di_chain(pair, "nak") == "e8020201 ---> [e8010002]"
