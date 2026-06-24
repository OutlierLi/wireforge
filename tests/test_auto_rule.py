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
            "cooldown": "500",
        })
        _ok(r)
        assert r["data"]["rule"]["execution"]["cooldown_ms"] == 500


# ═══════════════════════════════════════════════════════════════
# 3. add — 失败
# ═══════════════════════════════════════════════════════════════

class TestAddFail:
    def test_add_duplicate_id(self):
        exec_cmd("auto_rule", {"sub": "add", "id": "dup_rule", "match": "68.*16"})
        r = exec_cmd("auto_rule", {"sub": "add", "id": "dup_rule", "match": "68.*16"})
        _fail(r, "重复ID应失败")


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
                               "match": "68.*40.*03.*E8", "enable": "true"})
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
        exec_cmd("auto_rule", {"sub": "load", "file": "tests/rules.yaml"})
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
# 7. load YAML
# ═══════════════════════════════════════════════════════════════

class TestLoad:
    def test_load_yaml_success(self):
        r = exec_cmd("auto_rule", {"sub": "load", "file": "tests/rules.yaml"})
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
        exec_cmd("auto_rule", {"sub": "add", "id": "to_delete", "match": "00.*FF"})
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
        exec_cmd("auto_rule", {"sub": "add", "id": "hist_test", "match": "68.*16"})
        exec_cmd("auto_rule", {"sub": "test", "id": "hist_test",
                               "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16"})
        r = exec_cmd("auto_rule", {"sub": "history"})
        _ok(r)

    def test_history_filter_by_id(self):
        r = exec_cmd("auto_rule", {"sub": "history", "id": "hist_test"})
        _ok(r)
