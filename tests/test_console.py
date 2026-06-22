"""console 接口测试 — build resolve/encode, decode, command registry。"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd, list_cmds, get_cmd


# ═══════════════════════════════════════════════════════════════
# Command Registry
# ═══════════════════════════════════════════════════════════════

class TestCommandRegistry:
    def test_list_cmds(self):
        cmds = list_cmds()
        names = [c["name"] for c in cmds]
        assert "build" in names
        assert "decode" in names
        for c in cmds:
            assert "params" in c
            for p in c["params"]:
                assert "name" in p
                assert "type" in p
                assert "required" in p

    def test_get_cmd(self):
        b = get_cmd("build")
        assert b is not None
        assert b["name"] == "build"
        d = get_cmd("decode")
        assert d is not None
        assert get_cmd("nonexistent") is None


# ═══════════════════════════════════════════════════════════════
# Build — resolve
# ═══════════════════════════════════════════════════════════════

class TestBuildResolve:
    def test_resolve_dlt645_downlink(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "dir": "downlink",
            "resolve": True,
        })
        assert r.success
        out = r.output
        assert out["protocol"] == "dlt645_2007"
        assert "read_data_request" in out["variant_id"]
        assert len(r.path) > 0

    def test_resolve_dlt645_uplink_with_di(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000",
            "dir": "uplink", "resolve": True,
        })
        assert r.success
        schema = r.output["input_schema"]
        names = [f["name"] for f in schema]
        assert "freeze_year" in names
        assert "freeze_month" in names
        assert "freeze_day" in names
        assert "freeze_hour" in names
        assert all(f["required"] for f in schema)

    def test_resolve_csg(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x03", "dir": "downlink", "di": "E8000301",
            "resolve": True,
        })
        assert r.success
        assert "csg_2016" in r.output["protocol"]
        assert len(r.path) > 0

    def test_resolve_derived_fields_present(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "dir": "downlink",
            "resolve": True,
        })
        assert r.success
        derived = r.output.get("derived_fields", {})
        assert "control" in derived
        ctrl = derived["control"]
        assert "func" in ctrl
        assert "dir" in ctrl
        # derived fields should NOT be in input_schema
        schema_names = [f["name"] for f in r.output["input_schema"]]
        for name in schema_names:
            assert name not in ("control", "func", "dir", "afn")


# ═══════════════════════════════════════════════════════════════
# Build — encode
# ═══════════════════════════════════════════════════════════════

class TestBuildEncode:
    def test_build_dlt645_ok(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "dir": "downlink",
            "di": "00010000",
        })
        assert r.success
        assert len(r.frame_hex) > 10
        assert "FE" in r.frame_hex or "68" in r.frame_hex

    def test_build_dlt645_with_business_fields(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000",
            "dir": "uplink",
            "freeze_year": "26", "freeze_month": "06",
            "freeze_day": "21", "freeze_hour": "20",
        })
        assert r.success
        assert len(r.frame_hex) > 15

    def test_build_csg_ok(self):
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x03", "dir": "downlink", "di": "E8000301",
        })
        assert r.success
        assert len(r.frame_hex) > 8

    def test_build_missing_business_fields(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "0x11", "di": "00010000",
            "dir": "uplink",
        })
        assert not r.success
        assert "business" in r.error.lower() or "input_schema" in str(r.output)

    def test_build_bad_route(self):
        r = exec_cmd("build", {
            "proto": "csg", "di": "E8999999",
        })
        assert not r.success
        assert "route" in r.error.lower() or "No route" in r.error

    def test_build_ambiguous_route_requires_di(self):
        r = exec_cmd("build", {"proto": "csg", "afn": "0x04"})
        assert not r.success
        assert "di" in r.error.lower()
        assert "E8020404" in r.error

    def test_build_bad_hex_param(self):
        r = exec_cmd("build", {
            "proto": "dlt645", "func": "nothex",
        })
        assert not r.success

    def test_build_has_path_on_failure(self):
        r = exec_cmd("build", {
            "proto": "csg", "di": "E8999999",
        })
        assert not r.success
        # 路径不可达时 path 为空
        assert isinstance(r.path, str)


# ═══════════════════════════════════════════════════════════════
# Decode
# ═══════════════════════════════════════════════════════════════

class TestDecode:
    def test_decode_dlt645_ok(self):
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
        })
        assert r.success
        assert "read_address" in r.path or "0x13" in r.path
        assert len(r.frame_hex) > 10

    def test_decode_csg_ok(self):
        r = exec_cmd("decode", {
            "proto": "csg",
            "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
        })
        assert r.success
        assert "csg" in r.path.lower() or "afn" in r.path.lower()

    def test_decode_missing_hex(self):
        r = exec_cmd("decode", {"proto": "dlt645"})
        assert not r.success
        assert "hex" in r.error.lower()

    def test_decode_invalid_hex(self):
        r = exec_cmd("decode", {"proto": "dlt645", "hex": "ZZ"})
        assert not r.success

    def test_decode_has_path(self):
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
        })
        assert r.success
        assert len(r.path) > 0

    def test_decode_output_has_values(self):
        r = exec_cmd("decode", {
            "proto": "dlt645",
            "hex": "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
        })
        assert r.success
        assert r.structured is not None
        assert "frame" in r.structured
        assert "wire" in r.structured
        assert len(r.structured["wire"].get("fields", [])) > 0
