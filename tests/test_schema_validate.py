from __future__ import annotations

import pytest

from console.build_resolver import InputField, encode, resolve
from console.schema_validate import validate_business_values
from protocol_tool.codecs.enum_codec import EnumValueError, resolve_enum_raw
from protocol_tool.codecs.enum_codec import EnumCodec
from protocol_tool.codecs.base import ByteWriter
from protocol_tool.ir.nodes import FieldNode
from protocol_tool.runtime.context import BuildContext


def test_resolve_enum_raw_rejects_unknown_string():
    values = {"0x00": "禁止上报", "0x01": "允许上报"}
    with pytest.raises(EnumValueError, match="invalid enum value 'invalid'"):
        resolve_enum_raw("invalid", values, field_name="enable")


def test_resolve_enum_raw_accepts_hex_string():
    values = {"0x01": "单相电子表"}
    assert resolve_enum_raw("01", values) == 1


def test_validate_business_values_top_level_enum():
    schema = [
        InputField(
            name="enable",
            type="enum",
            required=True,
            enum_values={"0x00": "禁止上报", "0x01": "允许上报"},
        ),
    ]
    errors = validate_business_values({"enable": "invalid"}, schema)
    assert len(errors) == 1
    assert "enable" in errors[0]


def test_validate_business_values_nested_array_enum():
    schema = [
        InputField(
            name="nodes",
            type="array",
            required=True,
            children=[
                InputField(name="node_addr", type="bcd", required=True, length=6),
                InputField(
                    name="device_type",
                    type="enum",
                    required=True,
                    enum_values={"0x01": "单相电子表", "0x02": "多功能表"},
                ),
            ],
        ),
    ]
    errors = validate_business_values(
        {
            "nodes": [
                {"node_addr": "000000000001", "device_type": "invalid"},
            ],
        },
        schema,
    )
    assert len(errors) == 1
    assert "nodes[0].device_type" in errors[0]


def test_validate_uint8_range():
    schema = [InputField(name="slave_count", type="uint8", required=True)]
    assert not validate_business_values({"slave_count": 10}, schema)
    errors = validate_business_values({"slave_count": 300}, schema)
    assert len(errors) == 1
    assert "out of range" in errors[0]


def test_validate_uint8_non_numeric():
    schema = [InputField(name="slave_count", type="uint8", required=True)]
    errors = validate_business_values({"slave_count": "abc"}, schema)
    assert len(errors) == 1
    assert "expected number" in errors[0]


def test_validate_bcd_hex_digits():
    schema = [InputField(name="master_addr", type="bcd", required=True, length=6)]
    assert not validate_business_values({"master_addr": "000000000001"}, schema)
    errors = validate_business_values({"master_addr": "00000000000G"}, schema)
    assert len(errors) == 1
    assert "invalid hex digits" in errors[0]


def test_validate_bcd_too_long():
    schema = [InputField(name="master_addr", type="bcd", required=True, length=6)]
    errors = validate_business_values({"master_addr": "1" * 20}, schema)
    assert len(errors) == 1
    assert "too long" in errors[0]


def test_validate_array_scalar_bcd_items():
    schema = [
        InputField(
            name="slave_addrs",
            type="array",
            required=True,
            children=[InputField(name="slave_addr", type="bcd", required=True, length=6)],
        ),
    ]
    errors = validate_business_values(
        {"slave_addrs": ["000000000001", "00000000000G"]},
        schema,
    )
    assert len(errors) == 1
    assert "slave_addrs[1]" in errors[0]


def test_validate_hex_payload():
    schema = [InputField(name="payload", type="hex", required=True, length=4)]
    assert not validate_business_values({"payload": "01020304"}, schema)
    errors = validate_business_values({"payload": "0102ZZ"}, schema)
    assert len(errors) == 1
    assert "invalid hex digits" in errors[0]


def test_validate_ascii_length():
    schema = [InputField(name="tag", type="ascii", required=True, length=2)]
    assert not validate_business_values({"tag": "AB"}, schema)
    errors = validate_business_values({"tag": "ABC"}, schema)
    assert len(errors) == 1
    assert "too long" in errors[0]


def test_validate_bcd_numeric():
    schema = [InputField(name="energy", type="bcd_numeric", required=True, length=4)]
    assert not validate_business_values({"energy": "123.45"}, schema)
    errors = validate_business_values({"energy": "12x3"}, schema)
    assert len(errors) == 1
    assert "invalid bcd_numeric" in errors[0]


def test_add_slave_invalid_bcd_rejected_by_encode():
    target = resolve({
        "proto": "csg",
        "afn": "04",
        "di": "E8020402",
        "dir": "downlink",
        "has_address": False,
    })
    with pytest.raises(ValueError, match="slave_addrs"):
        encode(target, {
            "slave_count": 1,
            "slave_addrs": ["00000000000G"],
        })


def test_add_slave_invalid_uint_rejected_by_encode():
    target = resolve({
        "proto": "csg",
        "afn": "04",
        "di": "E8020402",
        "dir": "downlink",
        "has_address": False,
    })
    with pytest.raises(ValueError, match="slave_count"):
        encode(target, {
            "slave_count": "abc",
            "slave_addrs": ["000000000001"],
        })


def test_enum_codec_encode_raises_on_invalid_value():
    codec = EnumCodec()
    field = FieldNode(
        id="enable",
        name="enable",
        type_ref="enum",
        params={"values": {"0x01": "允许上报"}},
    )
    with pytest.raises(EnumValueError):
        codec.encode(field, "invalid", ByteWriter(), BuildContext())
