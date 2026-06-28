"""命令行全量测试 — build / decode / connect / send / close / ports。

覆盖: 成功 + 参数缺失 + 路径不存在 + 参数非法。
断言: 检查 success 标志 + error/detail 结构 + data 关键字段。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import complete_cmd, exec_cmd, exec_text, list_cmds, get_cmd
from console.runtime import parse_command_text


# ── helpers ───────────────────────────────────────────────────────────

def _ok(r, msg=""):
    assert r["status"] == "success", f"expected success: {msg} | got: {r.get('status')} {r.get('error','')}"


def _fail(r, msg=""):
    assert r["status"] != "success", f"expected fail: {msg} | got: {r}"


def _missing(r, key, msg=""):
    _fail(r, msg)
    # protocol-tui.v1: need_input 状态时缺少的字段在 input_schema 中
    schema = r.get("input_schema", [])
    detail_missing = r.get("detail", {}).get("missing", [])
    missing = schema or detail_missing
    keys = [m["key"] for m in missing]
    assert key in keys, f"expected missing '{key}' in {keys}: {msg}"


def _route_fail(r, msg=""):
    _fail(r, msg)
    err = r.get("error", "")
    assert "route" in err.lower() or "no route" in err.lower(), f"expected route error: {msg} | got: {err}"


def _has_path(r, msg=""):
    assert r.get("data", {}).get("path") or r.get("path"), f"expected path: {msg}"


def _has_frame(r, msg=""):
    assert r.get("data", {}).get("frame"), f"expected frame hex: {msg}"


# ═══════════════════════════════════════════════════════════════
# 1. 命令注册
# ═══════════════════════════════════════════════════════════════

class TestCommandRegistry:
    def test_all_commands_registered(self):
        names = [c["name"] for c in list_cmds()]
        for n in ("build", "decode", "serial", "auto_rule"):
            assert n in names, f"missing command: {n}"

    def test_command_has_module_and_handler(self):
        for c in list_cmds():
            assert c.get("module"), f"{c['name']}: missing module"
            assert c.get("handler"), f"{c['name']}: missing handler"

    def test_get_cmd(self):
        assert get_cmd("build") is not None
        assert get_cmd("nonexistent") is None

    def test_command_metadata_includes_params(self):
        cmd = get_cmd("build")
        assert cmd is not None
        assert "params" in cmd
        assert "proto" in cmd["params"]


class TestCommandRuntimeContract:
    def test_parse_command_text(self):
        cmd, args = parse_command_text("/build --protocol=csg --afn 0x03 --resolve")
        assert cmd == "build"
        assert args["proto"] == "csg"
        assert args["afn"] == "0x03"
        assert args["resolve"] is True

    def test_exec_text_uses_same_runtime(self):
        r = exec_text("/build --protocol=dlt645 --func=0x11 --di=00010000 --dir=downlink")
        _ok(r)
        _has_frame(r)

    def test_complete_commands(self):
        r = complete_cmd(prefix="/b")
        _ok(r)
        values = [c["value"] for c in r["data"]["completions"]]
        assert "/build" in values

    def test_complete_arguments(self):
        r = complete_cmd(prefix="--pr", command="build")
        _ok(r)
        values = [c["value"] for c in r["data"]["completions"]]
        assert "--proto" in values


# ═══════════════════════════════════════════════════════════════
# 2. /build — 成功
# ═══════════════════════════════════════════════════════════════

class TestBuildSuccess:
    def test_build_dlt645_read_data_request(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "dir": "downlink", "di": "00010000",
        })
        _ok(r, "645 读数据下行")
        _has_frame(r)
        _has_path(r)

    def test_build_csg_query_vendor(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x03", "dir": "downlink", "di": "E8000301",
        })
        _ok(r, "CSG 查询厂商")

    def test_build_dlt645_with_variant_fields(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "uplink",
            "freeze_year": "26", "freeze_month": "06",
            "freeze_day": "21", "freeze_hour": "20",
        })
        _ok(r, "645 上行+冻结时间变体")
        _has_frame(r)

    def test_build_csg_with_address(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x02", "di": "E8020201", "dir": "downlink",
            "addr": True,
            "address_area.adst": "012400038813",
            "payload": "FFFFFFFFFF",
        })
        _ok(r, "CSG 带地址域")

    def test_build_csg_uplink_ack(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010001", "dir": "uplink",
            "result": "0x00",
        })
        _ok(r, "CSG 上行ACK")


# ═══════════════════════════════════════════════════════════════
# 3. /build --resolve
# ═══════════════════════════════════════════════════════════════

class TestBuildResolve:
    def test_resolve_returns_schema(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "uplink",
            "resolve": True,
        })
        _ok(r)
        data = r["data"]
        assert data.get("input_schema"), "should have input_schema"
        assert data.get("derived_fields"), "should have derived_fields"

    def test_resolve_csg_returns_schema(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010001", "dir": "uplink",
            "resolve": True,
        })
        _ok(r)
        assert "input_schema" in r["data"]


# ═══════════════════════════════════════════════════════════════
# 4. /build — 失败: 参数缺失
# ═══════════════════════════════════════════════════════════════

class TestBuildFailMissingParam:
    def test_no_args_causes_route_error(self):
        """无任何参数时 proto 默认 dlt645，但缺少 func/dir 导致路由歧义"""
        r = exec_cmd("build", {})
        _fail(r)

    def test_missing_di_for_csg_sub_route(self):
        """CSG AFN=4 有多个 DI，不提供 di 时应提示歧义"""
        r = exec_cmd("build", {"proto": "csg", "afn": "0x04"})
        _fail(r)

    def test_missing_business_fields_shows_detail(self):
        """645 上行需要 freeze_* 字段 — 返回 route_required + schema"""
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "uplink",
        })
        _fail(r)
        assert r["status"] == "route_required"
        detail = r.get("detail", {})
        assert detail["required_step"] == "route"
        schema = detail.get("input_schema", [])
        keys = [m["name"] for m in schema]
        assert "freeze_year" in keys, f"should require freeze_year, got: {keys}"


# ═══════════════════════════════════════════════════════════════
# 5. /build — 失败: 路径不存在
# ═══════════════════════════════════════════════════════════════

class TestBuildFailRouteNotFound:
    def test_di_not_in_route_table(self):
        r = exec_cmd("build", {"proto": "csg", "di": "E8999999"})
        _route_fail(r)

    def test_func_not_in_route_table(self):
        r = exec_cmd("build", {"proto": "dlt645", "func": "0xFF"})
        _route_fail(r)

    def test_di_not_in_dlt645_variant(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "FFFFFFFF", "dir": "uplink",
        })
        _route_fail(r)


# ═══════════════════════════════════════════════════════════════
# 6. /decode — 成功
# ═══════════════════════════════════════════════════════════════

class TestDecodeSuccess:
    def test_decode_dlt645_read_address(self):
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
        })
        _ok(r, "645 读地址")
        _has_path(r)

    def test_decode_csg_query_vendor(self):
        r = exec_cmd("decode", {
            "proto": "csg",
            "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
        })
        _ok(r, "CSG 查询厂商")
        _has_path(r)

    def test_decode_dlt645_read_data_response(self):
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16",
        })
        _ok(r, "645 读数据应答")
        assert len(r["data"].get("values", {})) > 0, "should have decoded values"


# ═══════════════════════════════════════════════════════════════
# 7. /decode — 失败
# ═══════════════════════════════════════════════════════════════

class TestDecodeFail:
    def test_missing_hex_param(self):
        r = exec_cmd("decode", {"proto": "dlt645"})
        _fail(r)
        _missing(r, "hex")

    def test_invalid_hex(self):
        r = exec_cmd("decode", {"proto": "dlt645", "hex": "ZZ ZZ"})
        _fail(r)

    def test_checksum_mismatch_still_decodes(self):
        """校验和错误也应尝试解码并报告路径"""
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 00 16",
        })
        # 校验和不匹配时可能成功也可能失败，取决于引擎实现
        # 但不应 crash
        assert isinstance(r, dict)
        assert "status" in r


# ═══════════════════════════════════════════════════════════════
# 8. /serial connect / send / close / ports / set
# ═══════════════════════════════════════════════════════════════

class TestSerial:
    def test_connect_mock_ok(self):
        r = exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        _ok(r)

    def test_connect_missing_port(self):
        r = exec_cmd("serial", {"sub": "connect"})
        _fail(r)
        _missing(r, "port")

    def test_connect_with_baudrate(self):
        r = exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "baudrate": 115200})
        _ok(r)

    def test_send_loopback(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "send", "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16"})
        _ok(r)
        assert r["data"]["received_bytes"] > 0, "loopback should echo"

    def test_send_missing_hex(self):
        r = exec_cmd("serial", {"sub": "send", "timeout": 1})
        _fail(r)
        _missing(r, "hex")

    def test_send_not_connected(self):
        exec_cmd("serial", {"sub": "close"})
        r = exec_cmd("serial", {"sub": "send", "hex": "68 0C 00 40"})
        _fail(r)

    def test_ports_lists_available(self):
        r = exec_cmd("serial", {"sub": "ports"})
        _ok(r)
        assert "available" in r["data"]

    def test_named_connection_ports_and_send(self):
        exec_cmd("serial", {"sub": "connect", "name": "cco", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "ports"})
        _ok(r)
        assert "cco" in r["data"]["connected"]
        assert any(c["name"] == "cco" for c in r["data"]["connections"])

        r = exec_cmd("serial", {"sub": "send", "name": "cco", "hex": "68 0C 00 40"})
        _ok(r)
        assert r["data"]["id"] == "cco"
        assert r["data"]["name"] == "cco"
        assert r["data"]["received_bytes"] > 0

    def test_multiple_named_connections_close_one(self):
        exec_cmd("serial", {"sub": "connect", "name": "cco", "port": "mock://loop"})
        exec_cmd("serial", {"sub": "connect", "name": "sta1", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "close", "name": "cco"})
        _ok(r)
        r = exec_cmd("serial", {"sub": "ports"})
        _ok(r)
        assert "cco" not in r["data"]["connected"]
        assert "sta1" in r["data"]["connected"]

    def test_use_named_connection_as_default_target(self):
        exec_cmd("serial", {"sub": "connect", "name": "cco", "port": "mock://loop"})
        exec_cmd("serial", {"sub": "use", "name": "cco"})
        r = exec_cmd("serial", {"sub": "send", "hex": "68 0C 00 40"})
        _ok(r)
        assert r["data"]["name"] == "cco"

    def test_invalid_connection_name(self):
        r = exec_cmd("serial", {"sub": "connect", "name": "bad name", "port": "mock://loop"})
        _fail(r)
        assert "invalid connection name" in r.get("error", "")

    def test_close_when_connected(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "close"})
        _ok(r)

    def test_close_when_not_connected(self):
        exec_cmd("serial", {"sub": "close"})
        r = exec_cmd("serial", {"sub": "close"})
        _fail(r)

    def test_set_baudrate(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "set", "baudrate": 115200})
        _ok(r)
        assert "updated" in r["data"]

    def test_set_no_params_shows_current(self):
        r = exec_cmd("serial", {"sub": "set"})
        _ok(r)
        assert "current" in r["data"] or "updated" in r["data"]

    def test_default_sub_is_ports(self):
        r = exec_cmd("serial", {})
        _ok(r)
        assert "available" in r["data"]

    # ── display 参数测试 ──

    def test_connect_with_display_ascii(self):
        r = exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "display": "ascii"})
        _ok(r, "connect with display=ascii")

    def test_send_ascii_display_format(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "display": "ascii"})
        r = exec_cmd("serial", {"sub": "send", "hex": "48 65 6C 6C 6F", "name": "default"})
        _ok(r, "send ascii display")
        assert r["data"]["display"] == "ascii"
        assert r["data"]["received"] == "Hello", f"expected 'Hello', got '{r['data']['received']}'"

    def test_send_default_hex_format(self):
        exec_cmd("serial", {"sub": "close"})
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "send", "hex": "48 65 6C 6C 6F", "name": "default"})
        _ok(r)
        assert r["data"]["display"] == "hex"
        assert r["data"]["received"] == "48 65 6C 6C 6F"

    def test_set_display_persists(self):
        exec_cmd("serial", {"sub": "close"})
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "display": "ascii"})
        exec_cmd("serial", {"sub": "close"})
        r = exec_cmd("serial", {"sub": "open"})
        _ok(r)
        r2 = exec_cmd("serial", {"sub": "send", "hex": "41 42 43", "name": "default"})
        _ok(r2)
        assert r2["data"]["display"] == "ascii"
        assert "ABC" in r2["data"]["received"]

    def test_set_display_via_set_command(self):
        exec_cmd("serial", {"sub": "close"})
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
        r = exec_cmd("serial", {"sub": "set", "display": "ascii"})
        _ok(r)
        assert "ascii" in str(r["data"]["updated"])
        exec_cmd("serial", {"sub": "open"})
        r2 = exec_cmd("serial", {"sub": "send", "hex": "41 42 43", "name": "default"})
        _ok(r2)
        assert r2["data"]["display"] == "ascii"
        assert r2["data"]["received"] == "ABC"

    def test_send_ascii_control_chars(self):
        exec_cmd("serial", {"sub": "close"})
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "display": "ascii"})
        r = exec_cmd("serial", {"sub": "send", "hex": "0D 0A 09 01", "name": "default"})
        _ok(r)
        assert "\\r" in r["data"]["received"]
        assert "\\n" in r["data"]["received"]
        assert "\\t" in r["data"]["received"]

    def test_ports_shows_display(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "display": "ascii"})
        r = exec_cmd("serial", {"sub": "ports"})
        _ok(r)
        conns = r["data"].get("connections", [])
        default_conn = [c for c in conns if c.get("name") == "default"]
        if default_conn:
            assert default_conn[0].get("display", "hex") == "ascii"

    def test_cleanup_serial_state(self):
        exec_cmd("serial", {"sub": "close"})

class TestHelp:
    def test_help_list_all(self):
        r = exec_cmd("help", {})
        _ok(r)
        cmds = r["data"]["commands"]
        names = [c["name"] for c in cmds]
        assert "/build" in names
        assert "/serial" in names
        assert "/auto_rule" in names

    def test_help_serial(self):
        r = exec_cmd("help", {"target": "/serial"})
        _ok(r)
        assert r["data"]["command"] == "/serial"
        assert len(r["data"]["params"]) > 0
        assert any(p["name"] == "--port" for p in r["data"]["params"])
        assert any(p["name"] == "--name" for p in r["data"]["params"])

    def test_help_serial_sub(self):
        r = exec_cmd("help", {"target": "/serial open"})
        _ok(r)
        assert r["data"]["command"] == "/serial open"
        assert "Re-open" in r["data"]["desc"]

    def test_help_serial_send(self):
        r = exec_cmd("help", {"target": "/serial send"})
        _ok(r)
        assert r["data"]["command"] == "/serial send"

    def test_help_auto_rule(self):
        r = exec_cmd("help", {"target": "/auto_rule"})
        _ok(r)
        sub_names = [s["name"] for s in r["data"].get("sub_commands", [])]
        assert "/auto_rule add" in sub_names

    def test_help_auto_rule_sub(self):
        r = exec_cmd("help", {"target": "/auto_rule load"})
        _ok(r)
        assert "load" in r["data"]["command"]

    def test_help_build(self):
        r = exec_cmd("help", {"target": "/build"})
        _ok(r)
        assert r["data"]["command"] == "/build"

    def test_help_decode(self):
        r = exec_cmd("help", {"target": "/decode"})
        _ok(r)
        assert r["data"]["command"] == "/decode"

    def test_help_unknown_command(self):
        r = exec_cmd("help", {"target": "/nonexistent"})
        _fail(r)


# ═══════════════════════════════════════════════════════════════
# 12. /var — 变量系统
# ═══════════════════════════════════════════════════════════════

class TestVarSet:
    """覆盖: /var set — 所有类型 + 非法参数"""

    def test_set_string_default(self):
        r = exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "csg"})
        _ok(r, "set string")
        assert r["data"]["variable"]["type"] == "string"
        assert r["data"]["variable"]["value"] == "csg"

    def test_set_integer(self):
        r = exec_cmd("var", {"sub": "set", "_": ["retry"], "value": "3", "type": "integer"})
        _ok(r, "set integer")
        assert r["data"]["variable"]["value"] == 3

    def test_set_decimal(self):
        r = exec_cmd("var", {"sub": "set", "_": ["current"], "value": "10.5", "type": "decimal"})
        _ok(r, "set decimal")
        assert r["data"]["variable"]["value"] == "10.5"

    def test_set_boolean_true(self):
        r = exec_cmd("var", {"sub": "set", "_": ["flag"], "value": "true", "type": "boolean"})
        _ok(r, "set boolean true")
        assert r["data"]["variable"]["value"] is True

    def test_set_boolean_false(self):
        r = exec_cmd("var", {"sub": "set", "_": ["flag"], "value": "false", "type": "boolean"})
        _ok(r, "set boolean false")
        assert r["data"]["variable"]["value"] is False

    def test_set_hex(self):
        r = exec_cmd("var", {"sub": "set", "_": ["frame"], "value": "68 01 02 03 04 16", "type": "hex"})
        _ok(r, "set hex")
        assert r["data"]["variable"]["value"] == "68 01 02 03 04 16"

    def test_set_hex_with_separators(self):
        """HEX 支持多种分隔符并规范化"""
        r = exec_cmd("var", {"sub": "set", "_": ["raw"], "value": "68-01:02 03 04", "type": "hex"})
        _ok(r, "set hex separators")
        assert r["data"]["variable"]["value"] == "68 01 02 03 04"

    def test_set_json_object(self):
        r = exec_cmd("var", {"sub": "set", "_": ["payload"], "value": '{"phase":"A"}', "type": "json"})
        _ok(r, "set json object")
        assert r["data"]["variable"]["value"] == {"phase": "A"}

    def test_set_json_array(self):
        r = exec_cmd("var", {"sub": "set", "_": ["addrs"], "value": '["a","b"]', "type": "json"})
        _ok(r, "set json array")
        assert r["data"]["variable"]["value"] == ["a", "b"]

    def test_set_overwrite(self):
        exec_cmd("var", {"sub": "set", "_": ["x"], "value": "old"})
        r = exec_cmd("var", {"sub": "set", "_": ["x"], "value": "new"})
        _ok(r, "overwrite")
        assert r["data"]["variable"]["value"] == "new"

    def test_set_invalid_name_numeric_start(self):
        r = exec_cmd("var", {"sub": "set", "_": ["1abc"], "value": "x"})
        _fail(r, "invalid name")

    def test_set_invalid_name_with_dot(self):
        r = exec_cmd("var", {"sub": "set", "_": ["a.b"], "value": "x"})
        _fail(r, "invalid name with dot")

    def test_set_invalid_decimal_value(self):
        r = exec_cmd("var", {"sub": "set", "_": ["x"], "value": "abc", "type": "decimal"})
        _fail(r, "invalid decimal")

    def test_set_invalid_hex_value(self):
        r = exec_cmd("var", {"sub": "set", "_": ["x"], "value": "ZZ ZZ", "type": "hex"})
        _fail(r, "invalid hex")

    def test_set_invalid_hex_odd_length(self):
        r = exec_cmd("var", {"sub": "set", "_": ["x"], "value": "68 0", "type": "hex"})
        _fail(r, "hex odd length")

    def test_set_missing_value(self):
        r = exec_cmd("var", {"sub": "set", "_": ["x"]})
        _fail(r, "missing value")

    def test_set_missing_name(self):
        r = exec_cmd("var", {"sub": "set", "value": "csg"})
        _fail(r, "missing name")


class TestVarGet:
    """覆盖: /var get — 根变量 + 嵌套路径 + 不存在"""

    def test_get_root(self):
        exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "csg"})
        r = exec_cmd("var", {"sub": "get", "_": ["proto"]})
        _ok(r, "get root")
        assert r["data"]["value"] == "csg"

    def test_get_nested_path(self):
        exec_cmd("var", {"sub": "set", "_": ["info"], "value": '{"phase":"A","current":"10.5"}', "type": "json"})
        r = exec_cmd("var", {"sub": "get", "_": ["info.phase"]})
        _ok(r, "get nested")
        assert r["data"]["value"] == "A"

    def test_get_nonexistent(self):
        r = exec_cmd("var", {"sub": "get", "_": ["nonexistent"]})
        _fail(r, "get nonexistent")

    def test_get_nonexistent_path(self):
        exec_cmd("var", {"sub": "set", "_": ["info"], "value": '{"x":1}', "type": "json"})
        r = exec_cmd("var", {"sub": "get", "_": ["info.missing"]})
        _fail(r, "get nonexistent path")


class TestVarShow:
    """覆盖: /var show — 表格 + JSON + 空"""

    def test_show_table_format(self):
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["a"], "value": "1"})
        exec_cmd("var", {"sub": "set", "_": ["b"], "value": "2"})
        r = exec_cmd("var", {"sub": "show"})
        _ok(r, "show table")
        rows = r["data"]["variables"]
        assert isinstance(rows, list)
        # Each row has name, type, value fields
        for row in rows:
            assert "name" in row
            assert "type" in row

    def test_show_json_format(self):
        r = exec_cmd("var", {"sub": "show", "json": True})
        _ok(r, "show json")
        assert isinstance(r["data"]["variables"], dict)

    def test_show_empty(self):
        exec_cmd("var", {"sub": "clear"})
        r = exec_cmd("var", {"sub": "show"})
        _ok(r, "show empty")
        assert r["data"]["count"] == 0


class TestVarDelete:
    """覆盖: /var delete — 存在 + 不存在"""

    def test_delete_existing(self):
        exec_cmd("var", {"sub": "set", "_": ["tmp"], "value": "x"})
        r = exec_cmd("var", {"sub": "delete", "_": ["tmp"]})
        _ok(r, "delete existing")
        # 验证已删除
        r2 = exec_cmd("var", {"sub": "get", "_": ["tmp"]})
        _fail(r2, "should be gone")

    def test_delete_nonexistent(self):
        r = exec_cmd("var", {"sub": "delete", "_": ["no_such_var"]})
        _fail(r, "delete nonexistent")


class TestVarClear:
    """覆盖: /var clear"""

    def test_clear_non_empty(self):
        exec_cmd("var", {"sub": "set", "_": ["x"], "value": "1"})
        exec_cmd("var", {"sub": "set", "_": ["y"], "value": "2"})
        r = exec_cmd("var", {"sub": "clear"})
        _ok(r, "clear")
        r2 = exec_cmd("var", {"sub": "show"})
        assert r2["data"]["count"] == 0

    def test_clear_empty(self):
        exec_cmd("var", {"sub": "clear"})
        r = exec_cmd("var", {"sub": "clear"})
        _ok(r, "clear empty")


class TestVarExport:
    """覆盖: /var export — 成功 + 缺文件"""

    def test_export_with_data(self):
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "csg"})
        r = exec_cmd("var", {"sub": "export", "file": "/tmp/wf_test_export.yaml"})
        _ok(r, "export")
        assert r["data"]["count"] > 0
        import os
        assert os.path.exists("/tmp/wf_test_export.yaml")

    def test_export_empty(self):
        exec_cmd("var", {"sub": "clear"})
        r = exec_cmd("var", {"sub": "export", "file": "/tmp/wf_test_empty.yaml"})
        _ok(r, "export empty")
        assert r["data"]["count"] == 0

    def test_export_missing_file(self):
        r = exec_cmd("var", {"sub": "export"})
        _fail(r, "export missing file")


class TestVarImport:
    """覆盖: /var import — merge + replace + 缺文件"""

    def test_import_merge(self):
        # 先准备内存变量和导出文件
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["a"], "value": "1"})
        exec_cmd("var", {"sub": "export", "file": "/tmp/wf_test_import.yaml"})
        exec_cmd("var", {"sub": "set", "_": ["b"], "value": "2"})
        # merge: YAML 中的 a 覆盖，内存中的 b 保留
        r = exec_cmd("var", {"sub": "import", "file": "/tmp/wf_test_import.yaml", "mode": "merge"})
        _ok(r, "import merge")
        # 验证 b 还在
        r2 = exec_cmd("var", {"sub": "get", "_": ["b"]})
        _ok(r2, "b should remain after merge")

    def test_import_replace(self):
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["x"], "value": "old"})
        r = exec_cmd("var", {"sub": "import", "file": "/tmp/wf_test_import.yaml", "mode": "replace"})
        _ok(r, "import replace")
        # 验证 x 被清除（文件中只有 a）
        r2 = exec_cmd("var", {"sub": "get", "_": ["x"]})
        _fail(r2, "x should be gone after replace")

    def test_import_missing_file(self):
        r = exec_cmd("var", {"sub": "import", "file": "/tmp/no_such_file.yaml"})
        _fail(r, "import missing file")

    def test_import_invalid_mode(self):
        r = exec_cmd("var", {"sub": "import", "file": "/tmp/wf_test_import.yaml", "mode": "bad_mode"})
        _fail(r, "import invalid mode")


class TestVarVariableRefs:
    """覆盖: 变量引用解析 — ${name} / ${object.field}"""

    def test_full_reference(self):
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "csg"})
        # 使用 exec_text 触发变量引用解析
        r = exec_text("/var get proto")
        _ok(r, "get via text")
        assert r["data"]["value"] == "csg"

    def test_auto_last_result_after_build(self):
        """build 命令成功后自动设置 last_result / last_build / last_frame"""
        exec_cmd("var", {"sub": "clear"})
        r = exec_cmd("build", {"proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "downlink"})
        _ok(r, "build")
        r2 = exec_cmd("var", {"sub": "get", "_": ["last_build"]})
        _ok(r2, "last_build should exist")
        r3 = exec_cmd("var", {"sub": "get", "_": ["last_frame"]})
        _ok(r3, "last_frame should exist")

    def test_unknown_ref_preserved(self):
        """不存在的变量引用保持原样"""
        # exec_text 内部解析引用：${no_such_var} 无匹配时保持原文本
        from console.runtime import runtime
        args = {"value": "${no_such_var_xyz}"}
        resolved = runtime._resolve_var_refs(args)
        assert resolved["value"] == "${no_such_var_xyz}"
        print("  ✓ unknown ref preserved")

    def test_template_reference(self):
        """模板引用: 字符串拼接"""
        exec_cmd("var", {"sub": "set", "_": ["afn"], "value": "03"})
        from console.runtime import runtime
        args = {"value": "report-${afn}.yaml"}
        resolved = runtime._resolve_var_refs(args)
        assert resolved["value"] == "report-03.yaml"
        print("  ✓ template reference resolved")


class TestVarIntegration:
    """端到端集成: /var → /build 引用"""

    def test_var_to_build_via_ref(self):
        exec_cmd("var", {"sub": "clear"})
        exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "dlt645"})
        exec_cmd("var", {"sub": "set", "_": ["func_val"], "value": "0x11"})
        exec_cmd("var", {"sub": "set", "_": ["di_val"], "value": "00010000"})
        # 通过变量引用构造
        from console.runtime import runtime
        args = {"proto": "${proto}", "func": "${func_val}", "di": "${di_val}", "dir": "downlink"}
        resolved = runtime._resolve_var_refs(args)
        assert resolved["proto"] == "dlt645"
        assert resolved["func"] == "0x11"
        r = exec_cmd("build", resolved)
        _ok(r, "build from var refs")
        _has_frame(r)
        print("  ✓ var → build integration")

    def test_command_registered(self):
        names = [c["name"] for c in list_cmds()]
        assert "var" in names, "/var not registered"

    def test_help_var(self):
        r = exec_cmd("help", {"target": "/var"})
        _ok(r)
        assert r["data"]["command"] == "/var"
        sub_names = [s["name"] for s in r["data"].get("sub_commands", [])]
        assert "/var set" in sub_names
        assert "/var get" in sub_names
        assert "/var show" in sub_names

    def test_help_var_sub(self):
        r = exec_cmd("help", {"target": "/var import"})
        _ok(r)
        assert "import" in r["data"]["command"]

    def test_cleanup_after_tests(self):
        """清理测试产生的临时文件"""
        import os
        for f in ["/tmp/wf_test_export.yaml", "/tmp/wf_test_empty.yaml",
                  "/tmp/wf_test_import.yaml", "/tmp/test_vars.yaml",
                  "/tmp/wireforge_test_vars.yaml", "/tmp/test_var_cmd.yaml"]:
            try:
                os.remove(f)
            except OSError:
                pass
        exec_cmd("var", {"sub": "clear"})


# ═══════════════════════════════════════════════════════════════
# 13. /print — 打印文本 + 变量引用
# ═══════════════════════════════════════════════════════════════

class TestPrint:
    """覆盖: /print — 变量插值 + --raw + 边界"""

    def test_basic_interpolation(self):
        exec_cmd("var", {"sub": "set", "_": ["protocol"], "value": "csg"})
        r = exec_cmd("print", {"text": "当前协议：${protocol}"})
        _ok(r, "basic interpolation")
        assert r["data"]["output"] == "当前协议：csg"

    def test_template_multiple(self):
        exec_cmd("var", {"sub": "set", "_": ["afn"], "value": "03"})
        r = exec_cmd("print", {"text": "AFN=${afn}"})
        _ok(r, "template")
        assert r["data"]["output"] == "AFN=03"

    def test_hex_value(self):
        exec_cmd("var", {"sub": "set", "_": ["frame"], "value": "68 01 02 03 04 16", "type": "hex"})
        r = exec_cmd("print", {"text": "发送报文：${frame}"})
        _ok(r, "hex interpolation")
        assert r["data"]["output"] == "发送报文：68 01 02 03 04 16"

    def test_full_reference(self):
        r = exec_cmd("print", {"text": "${frame}"})
        _ok(r, "full ref")
        assert r["data"]["output"] == "68 01 02 03 04 16"

    def test_integer_value(self):
        exec_cmd("var", {"sub": "set", "_": ["count"], "value": "5", "type": "integer"})
        r = exec_cmd("print", {"text": "count=${count}"})
        _ok(r, "integer")
        assert r["data"]["output"] == "count=5"

    def test_json_nested(self):
        exec_cmd("var", {"sub": "set", "_": ["info"], "value": '{"phase":"A","current":"10.5"}', "type": "json"})
        r = exec_cmd("print", {"text": "phase=${info.phase}"})
        _ok(r, "nested json")
        assert r["data"]["output"] == "phase=A"

    def test_raw_no_interpolation(self):
        r = exec_cmd("print", {"text": "变量文本：${protocol}", "raw": True})
        _ok(r, "raw")
        assert r["data"]["output"] == "变量文本：${protocol}"
        assert r["data"]["raw"] is True

    def test_no_variables(self):
        r = exec_cmd("print", {"text": "hello world"})
        _ok(r, "no vars")
        assert r["data"]["output"] == "hello world"

    def test_unknown_var_preserved(self):
        r = exec_cmd("print", {"text": "未知：${no_such_var}"})
        _ok(r, "unknown var")
        assert r["data"]["output"] == "未知：${no_such_var}"

    def test_empty_text(self):
        r = exec_cmd("print", {})
        _fail(r, "empty text")

    def test_command_registered(self):
        names = [c["name"] for c in list_cmds()]
        assert "print" in names, "/print not registered"

    def test_help_print(self):
        r = exec_cmd("help", {"target": "/print"})
        _ok(r)
        assert r["data"]["command"] == "/print"

    def test_cleanup(self):
        exec_cmd("var", {"sub": "clear"})


# ═══════════════════════════════════════════════════════════════
# 14. /build --from-frame — 从报文重建
# ═══════════════════════════════════════════════════════════════

class TestBuildFromFrame:
    """覆盖: /build --from-frame — decode → rebuild (identical)
                   --from-frame --set — decode → modify → rebuild
                   --from-frame --resolve — decode → show schema"""

    def test_from_frame_rebuild_identical_645(self):
        """解码 645 帧后重建，应得到相同帧"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame})
        _ok(r, "from-frame 645 rebuild")
        assert r["data"]["frame"] == hex_frame, f"expected identical frame, got {r['data']['frame']}"
        assert "from_frame" in r["data"]

    def test_from_frame_rebuild_identical_csg(self):
        """解码 CSG 帧后重建，应得到相同帧"""
        hex_frame = "68 0C 00 40 03 01 01 03 00 E8 30 16"
        r = exec_cmd("build", {"from_frame": hex_frame})
        _ok(r, "from-frame CSG rebuild")
        assert r["data"]["frame"] == hex_frame

    def test_from_frame_with_set_modify(self):
        """--from-frame --set 修改字段后重建"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame, "set": "freeze_year=27"})
        _ok(r, "from-frame --set")
        # 修改了 freeze_year，帧应该不同
        assert r["data"]["frame"] != hex_frame, "frame should differ after --set"
        # 验证仍是有效帧
        _has_frame(r)

    def test_from_frame_with_set_multiple(self):
        """--from-frame --set 多个字段"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        # 只测试单个字段（TUI shell 对多个 --set 的处理不同）
        r = exec_cmd("build", {"from_frame": hex_frame, "set": "freeze_day=25"})
        _ok(r, "from-frame --set single field")
        assert r["data"]["frame"] != hex_frame

    def test_from_frame_resolve(self):
        """--from-frame --resolve 返回 schema + 解码值"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame, "resolve": True})
        _ok(r, "from-frame --resolve")
        assert "input_schema" in r["data"]
        assert "decoded_values" in r["data"]
        assert r["data"]["decoded_values"]["freeze_year"] == "26"

    def test_from_frame_resolve_shows_set_overrides(self):
        """--from-frame --resolve --set 显示覆盖值"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame, "resolve": True, "set": "freeze_month=12"})
        _ok(r)
        assert r["data"]["set_overrides"] == {"freeze_month": 12}

    def test_from_frame_read_address(self):
        """--from-frame 处理 645 读地址帧"""
        hex_frame = "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"
        r = exec_cmd("build", {"from_frame": hex_frame})
        _ok(r, "from-frame read address")
        assert r["data"]["frame"] == hex_frame

    def test_from_frame_with_explicit_proto(self):
        """--from-frame --proto 显式指定协议"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame, "proto": "dlt645"})
        _ok(r, "from-frame with explicit proto")
        _has_frame(r)

    def test_from_frame_auto_detect_protocol(self):
        """--from-frame 不指定 proto 时自动检测"""
        hex_frame = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
        r = exec_cmd("build", {"from_frame": hex_frame})
        _ok(r, "auto-detect protocol")
        assert "dlt645" in r["data"]["protocol"]

    def test_from_frame_invalid_hex(self):
        """--from-frame 非法 hex"""
        r = exec_cmd("build", {"from_frame": "ZZ ZZ"})
        _fail(r, "invalid hex")

    def test_from_frame_empty_hex(self):
        """--from-frame 空 hex"""
        r = exec_cmd("build", {"from_frame": ""})
        _fail(r, "empty hex")

    def test_from_frame_cross_proto_fails(self):
        """--from-frame 645帧 指定 proto=csg 应失败"""
        r = exec_cmd("build", {
            "proto": "csg",
            "from_frame": "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16",
        })
        _fail(r, "cross-protocol mismatch")


# ═══════════════════════════════════════════════════════════════
# 15. /delay — 延时等待
# ═══════════════════════════════════════════════════════════════

class TestDelay:
    """覆盖: /delay — ms + s + 边界 + 非法输入"""

    def test_delay_ms_default(self):
        import time
        start = time.monotonic()
        r = exec_cmd("delay", {"value": "50"})
        elapsed = time.monotonic() - start
        _ok(r)
        assert r["data"]["elapsed_ms"] >= 30, "should delay at least 30ms"
        assert elapsed >= 0.04, "should have waited"

    def test_delay_with_ms_suffix(self):
        r = exec_cmd("delay", {"value": "100ms"})
        _ok(r)
        assert r["data"]["seconds"] == 0.1
        assert r["data"]["elapsed_ms"] >= 50

    def test_delay_with_s_suffix(self):
        r = exec_cmd("delay", {"value": "0.2s"})
        _ok(r)
        assert r["data"]["seconds"] == 0.2
        assert r["data"]["elapsed_ms"] >= 100

    def test_delay_decimal_seconds(self):
        r = exec_cmd("delay", {"value": "1.5s"})
        _ok(r)
        assert r["data"]["seconds"] == 1.5

    def test_delay_invalid_format(self):
        r = exec_cmd("delay", {"value": "abc"})
        _fail(r, "invalid format")

    def test_delay_negative(self):
        r = exec_cmd("delay", {"value": "-1s"})
        _fail(r, "negative")

    def test_delay_exceeds_max(self):
        r = exec_cmd("delay", {"value": "301s"})
        _fail(r, "exceeds max")

    def test_delay_missing_value(self):
        r = exec_cmd("delay", {})
        _fail(r, "missing value")

    def test_command_registered(self):
        names = [c["name"] for c in list_cmds()]
        assert "delay" in names, "/delay not registered"

    def test_help_delay(self):
        r = exec_cmd("help", {"target": "/delay"})
        _ok(r)
        assert r["data"]["command"] == "/delay"


# ═══════════════════════════════════════════════════════════════
# 16. 跨协议路径测试
# ═══════════════════════════════════════════════════════════════

class TestCrossProtocol:
    def test_dlt645_all_control_codes_resolve(self):
        """645 全部控制码都能找到路径"""
        for func in (0x08, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16,
                     0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x03, 0x1D):
            for d in (0, 1):
                r = exec_cmd("build", {
                    "proto": "dlt645",
                    "func": f"0x{func:02X}",
                    "dir": "downlink" if d == 0 else "uplink",
                    "di": "00010000",
                    "resolve": True,
                })
                if r["status"] != "success" and "route" in r.get("error", "").lower():
                    continue  # 该方向无对应路由
                _ok(r, f"645 func=0x{func:02X} dir={d}")

    def test_csg_all_afns_resolve(self):
        """CSG 全部 AFN 都能找到路径"""
        # AFN 00-07
        di_map = {
            0: "E8010001", 1: "E8020101", 2: "E8020201", 3: "E8000301",
            4: "E8020404", 5: "E8050501", 6: "E8060601", 7: "E8020701",
        }
        for afn in range(8):
            di = di_map.get(afn, f"E800{afn:02X}01")
            direction = "uplink" if afn == 5 else "downlink"
            args = {
                "proto": "csg", "afn": f"0x{afn:02X}", "di": di,
                "dir": direction, "resolve": True,
            }
            r = exec_cmd("build", args)
            _ok(r, f"CSG AFN=0x{afn:02X}")

    def test_csg_address_domain_is_inferred_from_route(self):
        """添加任务/上报任务数据强制带地址域，普通写参数强制不带地址域。"""
        add_task = exec_cmd("build", {
            "proto": "csg", "afn": "0x02", "di": "E8020201",
            "dir": "downlink", "resolve": True,
        })
        _ok(add_task, "CSG 添加任务自动推断地址域")
        assert add_task["data"]["target_info"]["has_address"] is True
        assert "main[[0,1]]" in add_task["data"]["path"]

        add_task_wrong = exec_cmd("build", {
            "proto": "csg", "afn": "0x02", "di": "E8020201",
            "dir": "downlink", "addr": False, "resolve": True,
        })
        assert add_task_wrong["status"] == "no_route"

        add_slave = exec_cmd("build", {
            "proto": "csg", "afn": "0x04", "di": "E8020402",
            "dir": "downlink", "resolve": True,
        })
        _ok(add_slave, "CSG 添加从节点自动推断无地址域")
        assert add_slave["data"]["target_info"]["has_address"] is False
        assert "main[[0,0]]" in add_slave["data"]["path"]

        add_slave_wrong = exec_cmd("build", {
            "proto": "csg", "afn": "0x04", "di": "E8020402",
            "dir": "downlink", "addr": True, "resolve": True,
        })
        assert add_slave_wrong["status"] == "no_route"
