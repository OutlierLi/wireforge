"""/auto_rule 全量测试 — 覆盖所有子命令的成功和失败分支。"""

import sys, json, time
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd


def _ok(r, msg=""):
    assert r["status"] == "success", f"expected success: {msg} | got: {r}"


def _fail(r, msg=""):
    assert r["status"] != "success", f"expected fail: {msg} | got: {r}"


def _has(r, key, msg=""):
    assert key in r.get("data", {}), f"expected data.{key}: {msg}"


# ═══════════════════════════════════════════════════════════════
# 1. list (空规则)
# ═══════════════════════════════════════════════════════════════

class TestListEmpty:
    def test_list_empty(self):
        r = exec_cmd("auto_rule", {"sub": "list"})
        _ok(r, "空规则表")
        assert r["data"]["count"] == 0

    def test_list_no_sub_uses_list_default(self):
        """不传 sub 参数默认 list"""
        r = exec_cmd("auto_rule", {})
        _ok(r, "默认list")


# ═══════════════════════════════════════════════════════════════
# 2. add — 成功
# ═══════════════════════════════════════════════════════════════

class TestAddSuccess:
    def test_add_simple_rule(self):
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "test_rule_1",
            "name": "测试规则1",
            "match": "68.*16",
            "then": "/send --hex \"68 0D 00 80 00 01 01 00 01 E8 00 6B 16\"",
        })
        _ok(r, "添加简单规则")
        assert r["data"]["added"] == "test_rule_1"
        assert r["data"]["rule"]["enabled"] is True

    def test_add_rule_with_decode_condition(self):
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "test_rule_2",
            "name": "解码字段匹配",
            "field": "control.direction=uplink",
            "then": "/log --message \"matched\"",
        })
        _ok(r)
        assert r["data"]["rule"]["condition"]["type"] == "decoded"

    def test_add_rule_with_multiple_actions(self):
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "test_rule_3",
            "name": "多动作规则",
            "match": "AA.*BB",
            "then": "/send --hex \"11 22\"",
        })
        _ok(r)
        assert len(r["data"]["rule"]["actions"]) >= 1

    def test_add_rule_with_cooldown(self):
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "test_rule_4",
            "name": "带冷却",
            "match": "68.*16",
            "then": "/send --hex \"11 22\"",
            "cooldown": "500",
        })
        _ok(r)
        assert r["data"]["rule"]["execution"]["cooldown_ms"] == 500


# ═══════════════════════════════════════════════════════════════
# 3. add — 失败
# ═══════════════════════════════════════════════════════════════

class TestAddFail:
    def test_add_empty_fails(self):
        r = exec_cmd("auto_rule", {"sub": "add"})
        _fail(r, "空 add 应失败")
        assert r["status"] == "need_input"
        keys = [f["key"] for f in r.get("input_schema", [])]
        assert "id" in keys
        assert "match" in keys
        assert "then" in keys

    def test_add_missing_id_fails(self):
        r = exec_cmd("auto_rule", {
            "sub": "add",
            "match": "68.*16",
            "then": "/send --hex \"1122\"",
        })
        _fail(r)
        assert r["status"] == "need_input"
        keys = [f["key"] for f in r.get("input_schema", [])]
        assert keys == ["id"]

    def test_add_missing_then_fails(self):
        r = exec_cmd("auto_rule", {"sub": "add", "match": "68.*16"})
        _fail(r)
        assert r["status"] == "need_input"

    def test_add_missing_match_fails(self):
        r = exec_cmd("auto_rule", {"sub": "add", "then": "/send --hex \"11 22\""})
        _fail(r)
        assert r["status"] == "need_input"

    def test_add_duplicate_id(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "dup_rule", "match": "68.*16",
            "then": "/send --hex \"1122\"",
        })
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "dup_rule", "match": "68.*16",
            "then": "/send --hex \"1122\"",
        })
        _fail(r, "重复ID应失败")

    def test_add_then_shell_unquoted(self):
        """--then /print --text=success 无需引号或 JSON。"""
        from console.api import exec_text
        from console.handlers import auto_rule as ar

        r = exec_text("/auto_rule add --id shell_then --match 68.*16 --then /print --text=success")
        _ok(r)
        actions = ar._rules["shell_then"]["actions"]
        assert actions == [{"command": "/print", "args": {"text": "success"}}]
        exec_cmd("auto_rule", {"sub": "delete", "id": "shell_then"})


# ═══════════════════════════════════════════════════════════════
# 4. list / show (有规则)
# ═══════════════════════════════════════════════════════════════

class TestListShow:
    def test_list_has_rules(self):
        r = exec_cmd("auto_rule", {"sub": "list"})
        _ok(r)
        assert r["data"]["count"] > 0

    def test_show_existing(self):
        r = exec_cmd("auto_rule", {"sub": "show", "id": "test_rule_1"})
        _ok(r)
        assert r["data"]["rule"]["id"] == "test_rule_1"

    def test_show_nonexistent(self):
        r = exec_cmd("auto_rule", {"sub": "show", "id": "nonexistent"})
        _fail(r, "不存在的规则")


# ═══════════════════════════════════════════════════════════════
# 5. enable / disable
# ═══════════════════════════════════════════════════════════════

class TestEnableDisable:
    def test_disable_existing(self):
        r = exec_cmd("auto_rule", {"sub": "disable", "id": "test_rule_1"})
        _ok(r)
        assert r["data"]["enabled"] is False

    def test_enable_existing(self):
        r = exec_cmd("auto_rule", {"sub": "enable", "id": "test_rule_1"})
        _ok(r)
        assert r["data"]["enabled"] is True

    def test_enable_nonexistent(self):
        r = exec_cmd("auto_rule", {"sub": "enable", "id": "nonexistent"})
        _fail(r, "启用不存在的规则")


# ═══════════════════════════════════════════════════════════════
# 6. test — 匹配
# ═══════════════════════════════════════════════════════════════

class TestMatch:
    def test_test_match_hit(self):
        exec_cmd("auto_rule", {"sub": "add", "id": "match_test",
                               "match": "68.*40.*03.*E8", "enable": "true",
                               "then": "/send --hex \"1122\""})
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "match_test",
            "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_test_match_miss(self):
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "test_rule_1",
            "hex": "AA BB CC DD",
        })
        _ok(r)
        assert r["data"]["matched"] is False

    def test_test_disabled_rule_does_not_match(self):
        # 先加载并禁用
        exec_cmd("auto_rule", {"sub": "load", "file": "database/rules/auto_reply_rules.yaml"})
        exec_cmd("auto_rule", {"sub": "disable", "id": "csg_query_vendor_ack"})
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "csg_query_vendor_ack",
            "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
        })
        _ok(r)
        assert r["data"]["matched"] is False, "禁用规则不应匹配"

    def test_test_nonexistent_rule(self):
        r = exec_cmd("auto_rule", {"sub": "test", "id": "nonexistent", "hex": "AA BB"})
        _fail(r)

    def test_test_missing_hex(self):
        r = exec_cmd("auto_rule", {"sub": "test", "id": "test_rule_1"})
        _fail(r, "缺少 hex")


# ═══════════════════════════════════════════════════════════════
# 5b. composite match — all / any
# ═══════════════════════════════════════════════════════════════

class TestCompositeMatch:
    _QUERY_SLAVE_HEX = "68 0F 00 40 03 01 06 03 03 E8 00 00 20 58 16"

    def test_match_all_hit(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "all_hit",
            "match": {"all": ["060303E8", "0040"]},
            "then": "/send --hex \"11 22\"",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "all_hit",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_match_all_miss(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "all_miss",
            "match": {"all": ["060303E8", "FFFF"]},
            "then": "/send --hex \"11 22\"",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "all_miss",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False

    def test_match_any_hit(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "any_hit",
            "match": {"any": ["020102E8", "060303E8"]},
            "then": "/send --hex \"11 22\"",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "any_hit",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_match_any_miss(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "any_miss",
            "match": {"any": ["020102E8", "050300E8"]},
            "then": "/send --hex \"11 22\"",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "any_miss",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False

    def test_add_stores_composite_condition(self):
        r = exec_cmd("auto_rule", {
            "sub": "add", "id": "composite_store",
            "match": {"all": ["AA", "BB"]},
            "then": "/send --hex \"11 22\"",
        })
        _ok(r)
        cond = r["data"]["rule"]["condition"]
        assert "all" in cond
        assert len(cond["all"]) == 2


# ═══════════════════════════════════════════════════════════════
# 7. load YAML
# ═══════════════════════════════════════════════════════════════

class TestLoad:
    def test_load_yaml_success(self):
        r = exec_cmd("auto_rule", {"sub": "load", "file": "database/rules/auto_reply_rules.yaml"})
        _ok(r)
        assert r["data"]["loaded"] > 0

    def test_load_yaml_missing_file(self):
        r = exec_cmd("auto_rule", {"sub": "load", "file": "nonexistent.yaml"})
        _fail(r)

    def test_load_yaml_no_path(self):
        r = exec_cmd("auto_rule", {"sub": "load"})
        _fail(r, "缺少 file 参数")


# ═══════════════════════════════════════════════════════════════
# 8. delete
# ═══════════════════════════════════════════════════════════════

class TestDelete:
    def test_delete_existing(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "to_delete", "match": "00.*FF",
            "then": "/send --hex \"1122\"",
        })
        r = exec_cmd("auto_rule", {"sub": "delete", "id": "to_delete"})
        _ok(r)
        assert r["data"]["deleted"] == "to_delete"

        # 确认已删除
        r2 = exec_cmd("auto_rule", {"sub": "show", "id": "to_delete"})
        _fail(r2, "已删除应找不到")

    def test_delete_nonexistent(self):
        r = exec_cmd("auto_rule", {"sub": "delete", "id": "nonexistent"})
        _fail(r)


# ═══════════════════════════════════════════════════════════════
# 9. history
# ═══════════════════════════════════════════════════════════════

class TestHistory:
    def test_history_after_test(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "hist_test", "match": "68.*16",
            "then": "/send --hex \"1122\"",
        })
        exec_cmd("auto_rule", {"sub": "test", "id": "hist_test",
                               "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16"})
        r = exec_cmd("auto_rule", {"sub": "history"})
        _ok(r)

    def test_history_filter_by_id(self):
        r = exec_cmd("auto_rule", {"sub": "history", "id": "hist_test"})
        _ok(r)


# ═══════════════════════════════════════════════════════════════
# 10. update — 修改规则
# ═══════════════════════════════════════════════════════════════

class TestUpdate:
    def test_update_match_and_then(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "upd_rule",
            "match": "AA.*BB",
            "then": [{"command": "/send", "args": {"hex": "11 22"}}],
        })
        r = exec_cmd("auto_rule", {
            "sub": "update", "id": "upd_rule",
            "match": "CC.*DD",
            "then": [{"command": "/send", "args": {"hex": "33 44"}}],
        })
        _ok(r, "修改规则")
        assert r["data"]["updated"] == "upd_rule"
        assert r["data"]["rule"]["condition"]["pattern"] == "CC.*DD"
        assert r["data"]["rule"]["actions"][0]["args"]["hex"] == "33 44"

        hit = exec_cmd("auto_rule", {"sub": "test", "id": "upd_rule", "hex": "CC BB DD"})
        _ok(hit)
        assert hit["data"]["matched"] is True
        miss = exec_cmd("auto_rule", {"sub": "test", "id": "upd_rule", "hex": "AA BB"})
        _ok(miss)
        assert miss["data"]["matched"] is False

    def test_update_nonexistent(self):
        r = exec_cmd("auto_rule", {"sub": "update", "id": "no_such", "match": "00"})
        _fail(r)


# ═══════════════════════════════════════════════════════════════
# 11. decoded field — DI + 数据域字段组合匹配
# ═══════════════════════════════════════════════════════════════

class TestDecodedFieldMatch:
    _QUERY_SLAVE_HEX = "68 0F 00 40 03 01 06 03 03 E8 00 00 20 58 16"

    def test_decoded_field_only(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "dec_only",
            "field": "user_data.slave_count=32",
            "then": "/log --message matched",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "dec_only",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_decoded_field_miss(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "dec_miss",
            "field": "user_data.slave_count=99",
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "dec_miss",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False

    def test_composite_di_and_decoded_field(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_and_field",
            "match": {
                "all": [
                    "060303E8",
                    {"type": "decoded", "fields": {"user_data.slave_count": "32"}},
                ],
            },
            "then": [{"command": "/send", "args": {"hex": "AA BB"}}],
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "di_and_field",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_composite_di_hit_field_miss(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_hit_field_miss",
            "match": {
                "all": [
                    "060303E8",
                    {"type": "decoded", "fields": {"user_data.slave_count": "99"}},
                ],
            },
            "then": [{"command": "/send", "args": {"hex": "AA BB"}}],
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "di_hit_field_miss",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False


# ═══════════════════════════════════════════════════════════════
# 12. route sugar — di / afn / dir 语义匹配（decode + 归一化）
# ═══════════════════════════════════════════════════════════════

class TestRouteSugarMatch:
    _QUERY_SLAVE_HEX = "68 0F 00 40 03 01 06 03 03 E8 00 00 20 58 16"

    def test_top_level_di_normalized(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_sugar",
            "di": "E8030306",
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "di_sugar",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_match_object_di_afn_dir(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "route_all",
            "match": {"all": [{"di": "E8030306", "afn": "0x03", "dir": "downlink"}]},
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "route_all",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_match_di_and_payload_field(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_payload",
            "match": {"di": "E8030306", "slave_count": "32"},
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "di_payload",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True

    def test_shell_match_proto_route_payload_field(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "ack_wait",
            "match": True,
            "proto": "csg",
            "afn": "0x00",
            "di": "E8010001",
            "dir": "downlink",
            "wait_time": "0",
            "then": "/log --message ack",
        })
        show = exec_cmd("auto_rule", {"sub": "show", "id": "ack_wait"})
        fields = show["data"]["rule"]["condition"]["fields"]
        assert fields.get("user_data.wait_time") == "0"

    def test_match_di_payload_miss(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "di_payload_miss",
            "match": {"di": "E8030306", "slave_count": "99"},
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "di_payload_miss",
            "hex": self._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False


class TestDlt645ProtoMatch:
    _READ_DATA_HEX = "FE FE FE FE 68 01 00 00 00 00 00 68 11 04 33 33 34 33 B3 16"

    def test_dlt645_di_func_dir(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "645_route",
            "proto": "dlt645",
            "di": "00010000",
            "func": "0x11",
            "dir": "downlink",
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "645_route",
            "hex": self._READ_DATA_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True
        show = exec_cmd("auto_rule", {"sub": "show", "id": "645_route"})
        assert show["data"]["rule"]["proto"] == "dlt645"

    def test_dlt645_wrong_proto_misses(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "645_wrong_proto",
            "proto": "csg",
            "di": "00010000",
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "645_wrong_proto",
            "hex": self._READ_DATA_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is False

    def test_explicit_proto_csg_still_works(self):
        exec_cmd("auto_rule", {
            "sub": "add", "id": "csg_explicit",
            "proto": "csg",
            "di": "E8030306",
            "then": "/log",
        })
        r = exec_cmd("auto_rule", {
            "sub": "test", "id": "csg_explicit",
            "hex": TestRouteSugarMatch._QUERY_SLAVE_HEX,
        })
        _ok(r)
        assert r["data"]["matched"] is True


class TestRxTrigger:
    def test_rx_triggers_print_action(self, capsys):
        import time
        from wireforge_serial.api import get_connection

        exec_cmd("serial", {"sub": "close", "to": "default"})
        exec_cmd("serial", {"sub": "connect", "to": "default", "port": "mock://loop"})
        exec_cmd("auto_rule", {
            "sub": "add",
            "id": "rx_print",
            "match": "68.*16",
            "then": "/print",
            "text": "success",
        })
        capsys.readouterr()
        transport = get_connection("default")
        assert transport is not None
        transport.write(bytes.fromhex("684416"))
        captured = ""
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            captured += capsys.readouterr().out
            if "success" in captured:
                break
            time.sleep(0.02)
        exec_cmd("serial", {"sub": "close", "to": "default"})
        assert "success" in captured

    def test_rx_respects_trigger_source(self, capsys):
        import time
        from wireforge_serial.api import get_connection

        exec_cmd("serial", {"sub": "connect", "to": "other", "port": "mock://loop"})
        exec_cmd("auto_rule", {
            "sub": "add",
            "id": "src_only_default",
            "source": "serial:default",
            "match": "68.*16",
            "then": "/print",
            "text": "hit",
        })
        capsys.readouterr()
        transport = get_connection("other")
        transport.write(bytes.fromhex("684416"))
        time.sleep(0.15)
        captured = capsys.readouterr().out
        exec_cmd("serial", {"sub": "close", "to": "other"})
        assert "hit" not in captured
