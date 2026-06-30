from agent_protocol.state_machine import _values_match, _verify_build_against_decode


SLAVE_ADDRS_SCHEMA = {
    "name": "slave_addrs",
    "type": "array",
    "children": [
        {"name": "slave_addr", "type": "bcd", "length": 6},
    ],
}


def test_values_match_enum_raw_against_build_input():
    actual = {"raw": 1, "label": "允许上报"}
    assert _values_match("0x01", actual, {"type": "enum"}) is True
    assert _values_match("01", actual, {"type": "enum"}) is True


def test_values_match_array_bcd_addresses_with_spacing():
    expected = ["000000000001", "00 00 00 00 00 02"]
    actual = ["000000000001", "000000000002"]
    assert _values_match(expected, actual, SLAVE_ADDRS_SCHEMA) is True


def test_verify_build_against_decode_enum_field():
    build_request = {
        "proto": "csg",
        "afn": "04",
        "di": "E8020404",
        "dir": "downlink",
        "enable": "0x01",
    }
    decode = {
        "values": {
            "user_data": {
                "afn": 4,
                "di": "E8 02 04 04",
                "dir": 0,
                "enable": {"raw": 1, "label": "允许上报"},
            }
        }
    }
    input_schema = [{"name": "enable", "type": "enum"}]
    check = _verify_build_against_decode(decode, build_request, input_schema)
    enable = next(item for item in check["checked_fields"] if item["field"] == "enable")
    assert enable["ok"] is True
