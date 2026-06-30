"""mock://auto _AutoRulePort 集成测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd
from console.handlers import auto_rule as auto_rule_mod
from wireforge_serial.transport import _AutoRulePort


@pytest.fixture(autouse=True)
def clear_rules():
    auto_rule_mod._rules.clear()
    auto_rule_mod._rule_history.clear()
    yield
    auto_rule_mod._rules.clear()
    auto_rule_mod._rule_history.clear()


QUERY_SLAVE_DOWNLINK = (
    "68 0F 00 40 03 01 06 03 03 E8 00 00 20 58 16"
)


class TestAutoRulePort:
    def test_no_rule_no_reply(self):
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == b""

    def test_send_action_reply(self):
        exec_cmd("auto_rule", {
            "sub": "add",
            "id": "send_reply",
            "match": "050300E8",
            "then": [{"command": "/send", "args": {"hex": "11 22 33"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex("050300E8"))
        assert port.read(4096) == bytes.fromhex("112233")

    def test_match_all_on_port(self):
        exec_cmd("auto_rule", {
            "sub": "add",
            "id": "all_port",
            "match": {"all": ["060303E8", "0040"]},
            "then": [{"command": "/send", "args": {"hex": "AA BB"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("AABB")

    def test_build_dynamic_query_slave_info(self):
        exec_cmd("auto_rule", {
            "sub": "add",
            "id": "build_slave_info",
            "match": {"all": ["060303E8", "0040"]},
            "then": [{
                "command": "build",
                "args": {
                    "proto": "csg",
                    "afn": "0x03",
                    "di": "E8040306",
                    "dir": "uplink",
                    "slave_total": 1024,
                    "response_slave_count": "$request.user_data.slave_count",
                    "slave_addrs": "$generated.slave_addrs",
                },
            }],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        reply = port.read(4096)
        assert reply.startswith(b"\x68")
        assert reply.endswith(b"\x16")
        assert b"\xe8\x03\x06\x03" in reply.lower() or b"\x06\x03\x06\xe8" in reply.lower() or len(reply) > 20

        decode_r = exec_cmd("decode", {
            "proto": "csg",
            "hex": reply.hex(" ").upper(),
        })
        assert decode_r["status"] == "success"
        values = decode_r["data"].get("values", {})
        ud = values.get("user_data") or {}
        payload = ud.get("di_payload") or ud.get("data_content", {}).get("di_payload") or {}
        count = payload.get("response_slave_count")
        if count is None:
            for k, v in ud.items():
                if k.endswith("response_slave_count"):
                    count = v
                    break
        assert int(count) == 32

    def test_rule_override_later_wins(self):
        """后添加的规则覆盖同 DI 的较早规则，只执行一条 then。"""
        exec_cmd("auto_rule", {
            "sub": "add", "id": "override_a",
            "match": "060303E8",
            "then": [{"command": "/send", "args": {"hex": "AA"}}],
        })
        exec_cmd("auto_rule", {
            "sub": "add", "id": "override_b",
            "match": "060303E8",
            "then": [{"command": "/send", "args": {"hex": "BB"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("BB")

    def test_delete_stops_reply(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "del_me",
            "match": "060303E8",
            "then": [{"command": "/send", "args": {"hex": "AA BB"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("AABB")

        exec_cmd("auto_rule", {"sub": "delete", "id": "del_me"})
        port2 = _AutoRulePort()
        port2.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port2.read(4096) == b""

    def test_update_changes_reply(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "upd_port",
            "match": "060303E8",
            "then": [{"command": "/send", "args": {"hex": "11 22"}}],
        })
        exec_cmd("auto_rule", {
            "sub": "update", "id": "upd_port",
            "then": [{"command": "/send", "args": {"hex": "33 44"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("3344")

    def test_di_and_decoded_field_on_port(self):
        """DI 匹配 + 数据域 slave_count 字段匹配后才回复。"""
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_field_port",
            "match": {
                "all": [
                    "060303E8",
                    {"type": "decoded", "fields": {"user_data.slave_count": "32"}},
                ],
            },
            "then": [{"command": "/send", "args": {"hex": "CC DD"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("CCDD")

        # slave_count=20 的帧不应命中
        wrong_count = "68 0F 00 40 03 01 06 03 03 E8 00 00 14 4C 16"
        port2 = _AutoRulePort()
        port2.write(bytes.fromhex(wrong_count.replace(" ", "")))
        assert port2.read(4096) == b""

    def test_match_any_branches(self):
        """any 多分支：DI 或 另一 DI 均可触发不同规则（后加覆盖同 pattern）。"""
        exec_cmd("auto_rule", {
            "sub": "add", "id": "any_a",
            "match": {"any": ["020102E8", "050300E8"]},
            "then": [{"command": "/send", "args": {"hex": "AA"}}],
        })
        exec_cmd("auto_rule", {
            "sub": "add", "id": "any_b",
            "match": "060303E8",
            "then": [{"command": "/send", "args": {"hex": "BB"}}],
        })
        port = _AutoRulePort()
        port.write(bytes.fromhex(QUERY_SLAVE_DOWNLINK.replace(" ", "")))
        assert port.read(4096) == bytes.fromhex("BB")
