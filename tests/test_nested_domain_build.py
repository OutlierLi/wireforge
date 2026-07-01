"""Build/compile tests for domain types — base protocol only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
IR_PATH = ROOT / "compiled" / "csg_2016.ir.json"


@pytest.fixture(scope="module", autouse=True)
def _compile_csg():
    from protocol_tool.compiler.pipeline import compile_protocol

    compile_protocol(str(REGISTRY), "csg_2016", output_dir=str(ROOT / "compiled"))


def test_frame_compiler_resolves_node_address_in_struct_array_items():
    from protocol_tool.compiler.frame_compiler import FrameCompiler
    from protocol_tool.compiler.loader import load_protocol
    from protocol_tool.compiler.resolver import Resolver

    unit = load_protocol(str(REGISTRY), "csg_2016")
    fc = FrameCompiler(unit, Resolver(unit))
    resolved = fc._resolve_field_yaml({
        "name": "slave_infos",
        "type": "array",
        "item_type": "struct",
        "item_params": {
            "fields": [
                {"name": "node_addr", "type": "node_address", "description": "从节点地址"},
                {"name": "device_type", "type": "uint8", "description": "设备类型"},
            ],
        },
        "count_ref": "response_slave_count",
    })
    addr = resolved["item_params"]["fields"][0]
    assert addr["type"] == "bcd"
    assert addr.get("length") == 6
    assert addr.get("byte_order") == "little"


def test_compile_resolves_node_address_in_base_struct_body():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    leaf = next(
        v for v in ir["leaves"].values()
        if v.get("name") == "csg_2016.afn03_query_mode_resp"
    )
    master = next(
        f for f in leaf["fields"]
        if f["name"] == "master_addr"
    )
    assert master["type_ref"] == "bcd"
    assert master["params"].get("length") == 6


def test_resolve_slave_addrs_array_schema():
    from console.build_resolver import resolve

    target = resolve({
        "proto": "csg",
        "afn": "03",
        "di": "E8040306",
        "dir": "uplink",
        "has_address": False,
    })
    addrs = next(f for f in target.input_schema if f.name == "slave_addrs")
    assert addrs.type == "array"
    assert len(addrs.children) == 1
    assert addrs.children[0].name == "slave_addr"
    assert addrs.children[0].type == "bcd"
    assert addrs.children[0].length == 6


def test_build_query_slave_info_resp_ten_addresses():
    from console.build_resolver import encode, resolve

    addrs = [f"{i:012d}" for i in range(1, 11)]
    target = resolve({
        "proto": "csg",
        "afn": "03",
        "di": "E8040306",
        "dir": "uplink",
        "has_address": False,
    })
    hex_out = encode(target, {
        "slave_total": 100,
        "response_slave_count": 10,
        "slave_addrs": addrs,
    })
    assert hex_out.endswith("16")
    assert len(hex_out.replace(" ", "")) > 40


def test_build_event_report_ctl_enable_hex_string():
    from console.build_resolver import encode, resolve

    target = resolve({
        "proto": "csg",
        "afn": "04",
        "di": "E8020404",
        "dir": "downlink",
        "has_address": False,
    })
    hex_out = encode(target, {"enable": "01"})
    assert "01" in hex_out.replace(" ", "")


def test_build_event_report_ctl_invalid_enum_rejected():
    from console.build_resolver import encode, resolve

    target = resolve({
        "proto": "csg",
        "afn": "04",
        "di": "E8020404",
        "dir": "downlink",
        "has_address": False,
    })
    with pytest.raises(ValueError, match="enable"):
        encode(target, {"enable": "99"})
