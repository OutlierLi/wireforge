"""Unit tests for TypeInferencer and SemanticValidator."""

from __future__ import annotations

import pytest

from protocol_extend.candidate import candidate_from_agent_field
from protocol_extend.fields import field_to_yaml, field_to_yaml_from_inferred, process_agent_fields
from protocol_extend.semantic_validator import validate_inferred
from protocol_extend.type_inferencer import infer_field


def _c(**kwargs):
    return candidate_from_agent_field({"name": "x", "desc": "测试", **kwargs})


class TestValueTableEnum:
    def test_device_type_becomes_enum_not_uint(self):
        cand = _c(
            name="device_type",
            desc="设备类型",
            bytes=2,
            evidence=["00H：单相表", "01H：三相表", "02H：采集器", "03H：集中器"],
            type="uint8",
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "enum"
        assert inf.codec["type"] == "enum"
        assert inf.codec["values"][0] == "单相表"
        assert inf.codec.get("length") == 2

    def test_agent_uint8_with_value_table_not_downgraded(self):
        yaml_out = field_to_yaml({
            "name": "device_type",
            "desc": "设备类型",
            "type": "uint8",
            "evidence": ["00H：单相表", "01H：三相表"],
        })
        assert yaml_out["type"] == "enum"
        assert "values" in yaml_out


class TestBoolEnum:
    def test_switch_bool_semantic_enum_yaml(self):
        cand = _c(
            name="switch_state",
            desc="开关",
            evidence=["0：关闭", "1：打开"],
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "bool"
        yaml_out = field_to_yaml_from_inferred(inf)
        assert yaml_out["type"] == "enum"
        assert yaml_out["values"] == {0: "关闭", 1: "打开"}


class TestNamedStatesEnum:
    def test_running_status_named_states(self):
        cand = _c(
            name="run_status",
            desc="运行状态",
            evidence=["运行状态：", "空闲", "抄表中", "升级中"],
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "enum"
        assert len(inf.codec["values"]) >= 2
        assert "enum_hex_values_missing" in inf.warnings or inf.confidence == "medium"


class TestDatetimeStruct:
    def test_datetime_subfields_alias(self):
        cand = candidate_from_agent_field({
            "name": "event_time",
            "desc": "事件时间",
            "type": "struct",
            "fields": [
                {"name": "year", "type": "bcd", "length": 1, "desc": "年"},
                {"name": "month", "type": "bcd", "length": 1, "desc": "月"},
                {"name": "day", "type": "bcd", "length": 1, "desc": "日"},
                {"name": "hour", "type": "bcd", "length": 1, "desc": "时"},
                {"name": "minute", "type": "bcd", "length": 1, "desc": "分"},
            ],
        })
        inf = infer_field(cand)
        assert inf.semantic_type == "object"
        assert inf.codec["type"] == "datetime_ymdhm"


class TestDecimal:
    def test_voltage_01v(self):
        cand = _c(
            name="voltage_a",
            desc="A相电压",
            bytes=2,
            evidence=["单位 0.1V，范围 0~300"],
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "decimal"
        assert inf.codec["type"] == "bcd_numeric"
        assert inf.codec.get("unit") == "V"


class TestAscii:
    def test_vendor_code_ascii(self):
        cand = _c(
            name="vendor_code",
            desc="厂商代码",
            evidence=["2字节 ASCII 字符串"],
            length=2,
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "string"
        assert inf.codec["type"] == "ascii"
        assert inf.codec["length"] == 2


class TestRawHex:
    def test_transparent_data(self):
        cand = _c(name="payload", desc="透明数据区", evidence=["厂家私有透明数据"])
        inf = infer_field(cand)
        assert inf.semantic_type == "raw_hex"
        assert inf.codec["type"] == "bytes"


class TestUnknownAndOverride:
    def test_unknown_warning(self):
        cand = _c(name="mystery", desc="未知字段")
        inf = infer_field(cand)
        assert inf.semantic_type == "unknown"
        warnings = validate_inferred(inf, cand)
        assert any("unknown" in w for w in warnings)

    def test_unknown_override_enum(self):
        cand = _c(
            name="mystery",
            desc="未知字段",
            semantic_override="enum",
            evidence=["00H：A", "01H：B"],
        )
        inf = infer_field(cand)
        assert inf.semantic_type == "enum"
        assert inf.overridden is True

    def test_unknown_confirm_allowed_via_process(self):
        _, report, warnings = process_agent_fields([{"name": "mystery", "desc": "未知"}])
        assert report[0]["semantic_type"] == "unknown"
        assert warnings


class TestIntegerFallback:
    def test_uint16_le_without_evidence(self):
        cand = _c(name="timeout", desc="超时(秒)", type="uint16_le")
        inf = infer_field(cand)
        assert inf.semantic_type == "integer"
        assert inf.codec["type"] == "uint16_le"

    def test_uint24_le_width(self):
        cand = _c(name="delay", desc="延时", type="uint24_le", bytes=3)
        inf = infer_field(cand)
        assert inf.codec["type"] == "uint24_le"


class TestNodeAddressDomainType:
    def test_scalar_node_address(self):
        cand = _c(name="slave_addr", desc="从节点地址", bytes=6)
        inf = infer_field(cand)
        assert inf.semantic_type == "node_address"
        yaml_out = field_to_yaml_from_inferred(inf)
        assert yaml_out["type"] == "node_address"
        assert "length" not in yaml_out

    def test_blacklist_address_list_array(self):
        yaml_out = field_to_yaml({
            "name": "blacklist_nodes",
            "desc": "黑名单节点地址列表",
            "type": "array",
            "count_ref": "resp_count",
            "item_name": "blacklist_node",
        })
        assert yaml_out["type"] == "array"
        assert yaml_out["item_type"] == "node_address"
        assert "item_params" not in yaml_out or "length" not in (yaml_out.get("item_params") or {})

    def test_bytes_six_with_address_desc_prefers_node_address(self):
        cand = _c(name="field_1", desc="节点地址", bytes=6, type="bytes")
        inf = infer_field(cand)
        assert inf.semantic_type == "node_address"
        assert inf.codec["type"] == "node_address"
