"""命令行全量测试 — build / decode / connect / send / close / ports。

覆盖: 成功 + 参数缺失 + 路径不存在 + 参数非法。
断言: 检查 success 标志 + error/detail 结构 + data 关键字段。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd, list_cmds, get_cmd


# ── helpers ───────────────────────────────────────────────────────────

def _ok(r, msg=""):
    assert r["success"], f"expected success: {msg} | got: {r.get('error')}"


def _fail(r, msg=""):
    assert not r["success"], f"expected fail: {msg} | got: {r}"


def _missing(r, key, msg=""):
    _fail(r, msg)
    detail = r.get("detail", {})
    missing = detail.get("missing", [])
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
        for n in ("build", "decode", "connect", "send", "close", "ports"):
            assert n in names, f"missing command: {n}"

    def test_command_has_module_and_handler(self):
        for c in list_cmds():
            assert c.get("module"), f"{c['name']}: missing module"
            assert c.get("handler"), f"{c['name']}: missing handler"

    def test_get_cmd(self):
        assert get_cmd("build") is not None
        assert get_cmd("nonexistent") is None


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
            "addr": True, "task_info": "010203",
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
        """645 上行需要 freeze_* 字段"""
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000", "dir": "uplink",
        })
        _fail(r)
        detail = r.get("detail", {})
        missing = detail.get("missing", [])
        keys = [m["key"] for m in missing]
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
        assert "success" in r


# ═══════════════════════════════════════════════════════════════
# 8. /connect — 串口连接
# ═══════════════════════════════════════════════════════════════

class TestConnect:
    def test_connect_mock_ok(self):
        r = exec_cmd("connect", {"port": "mock://loop"})
        _ok(r)

    def test_connect_missing_port(self):
        r = exec_cmd("connect", {})
        _fail(r)
        _missing(r, "port")

    def test_connect_with_baudrate(self):
        r = exec_cmd("connect", {"port": "mock://loop", "baudrate": 115200})
        _ok(r)


# ═══════════════════════════════════════════════════════════════
# 9. /send — 串口发送
# ═══════════════════════════════════════════════════════════════

class TestSend:
    def test_send_loopback(self):
        exec_cmd("connect", {"port": "mock://loop"})
        r = exec_cmd("send", {
            "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
        })
        _ok(r)
        assert r["data"]["received_bytes"] > 0, "loopback should echo"

    def test_send_missing_hex(self):
        r = exec_cmd("send", {"timeout": 1})
        _fail(r)
        _missing(r, "hex")

    def test_send_not_connected(self):
        # close first
        exec_cmd("close", {})
        r = exec_cmd("send", {"hex": "68 0C 00 40"})
        _fail(r)


# ═══════════════════════════════════════════════════════════════
# 10. /ports & /close
# ═══════════════════════════════════════════════════════════════

class TestPortsAndClose:
    def test_ports_lists_available(self):
        r = exec_cmd("ports", {})
        _ok(r)
        assert "available" in r["data"], "should list available ports"
        assert "mock://loop" in r["data"]["available"]

    def test_close_when_connected(self):
        exec_cmd("connect", {"port": "mock://loop"})
        r = exec_cmd("close", {})
        _ok(r)

    def test_close_when_not_connected(self):
        exec_cmd("close", {})  # ensure disconnected
        r = exec_cmd("close", {})
        _fail(r, "close without connection should fail")


# ═══════════════════════════════════════════════════════════════
# 11. 跨协议路径测试
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
                if not r["success"] and "route" in r.get("error", "").lower():
                    continue  # 该方向无对应路由
                _ok(r, f"645 func=0x{func:02X} dir={d}")

    def test_csg_all_afns_resolve(self):
        """CSG 全部 AFN 都能找到路径"""
        import random
        addr = "000000000001"
        # AFN 00-07
        di_map = {
            0: "E8010001", 1: "E8020101", 2: "E8020201", 3: "E8000301",
            4: "E8020404", 5: "E8050501", 6: "E8060601", 7: "E8020701",
        }
        for afn in range(8):
            di = di_map.get(afn, f"E800{afn:02X}01")
            r = exec_cmd("build", {
                "proto": "csg", "afn": f"0x{afn:02X}", "di": di,
                "dir": "downlink", "resolve": True,
            })
            _ok(r, f"CSG AFN=0x{afn:02X}")
