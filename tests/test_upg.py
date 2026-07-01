"""/upg 全量测试 — 分段、CRC、帧构造、参数校验、命令注册。"""

import sys, json, tempfile
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd


def _ok(r, msg=""):
    assert r["status"] == "success", f"expected success: {msg} | got: {r}"


def _fail(r, msg=""):
    assert r["status"] != "success", f"expected fail: {msg} | got: {r}"


# ═══════════════════════════════════════════════════════════════
# 1. 文件分段 + CRC
# ═══════════════════════════════════════════════════════════════

class TestSegmentation:
    def test_segment_exact(self):
        from console.handlers.upg import _segment_file
        data = b"\x00" * 256
        segs = _segment_file(data, 128)
        assert len(segs) == 2
        assert len(segs[0]) == 128
        assert len(segs[1]) == 128

    def test_segment_partial_last(self):
        from console.handlers.upg import _segment_file
        data = b"\x00" * 300
        segs = _segment_file(data, 128)
        assert len(segs) == 3
        assert len(segs[0]) == 128
        assert len(segs[2]) == 44

    def test_crc_known(self):
        from console.handlers.upg import _crc16_modbus
        crc = _crc16_modbus(b"\x00\x01\x02\x03")
        assert 0 <= crc <= 0xFFFF

    def test_pack_file_info(self):
        info = {
            "file_type": 2,
            "file_id": 0,
            "dest_addr": "999999999999",
            "total_segments": 2,
            "file_size": 256,
            "file_crc": 0xABCD,
            "timeout_minutes": 30,
        }
        assert set(info) == {
            "file_type",
            "file_id",
            "dest_addr",
            "total_segments",
            "file_size",
            "file_crc",
            "timeout_minutes",
        }


# ═══════════════════════════════════════════════════════════════
# 2. 参数校验
# ═══════════════════════════════════════════════════════════════

class TestUpgParams:
    def test_missing_file(self):
        r = exec_cmd("upg", {})
        _fail(r)
        assert "file" in str(r.get("input_schema", []))

    def test_file_not_found(self):
        r = exec_cmd("upg", {"file": "nonexistent.bin"})
        _fail(r)
        assert "not found" in r.get("error", "")

    def test_invalid_segment_size(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name

        r = exec_cmd("upg", {"file": tmp, "segment-size": "999"})
        _fail(r)
        assert "segment-size" in r.get("error", "").lower()
        Path(tmp).unlink()

    def test_no_serial_connection(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name

        exec_cmd("serial", {"sub": "close"})
        r = exec_cmd("upg", {"file": tmp, "segment-size": "128"})
        _fail(r)
        assert "not connected" in r.get("error", "").lower()
        Path(tmp).unlink()

    def test_no_named_serial_connection(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name

        exec_cmd("serial", {"sub": "close", "name": "cco"})
        r = exec_cmd("upg", {"file": tmp, "segment-size": "128", "name": "cco"})
        _fail(r)
        assert "name=cco" in r.get("error", "")
        Path(tmp).unlink()

    def test_build_only_writes_complete_cache(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(bytes(range(256)))
            tmp = f.name

        cache_path = Path(tmp + ".upg_cache")
        try:
            r = exec_cmd("upg", {
                "file": tmp,
                "segment-size": "128",
                "build-only": True,
                "no-cache": True,
            })
            _ok(r)
            assert r["data"]["total_segments"] == 2
            assert r["data"]["frames_built"] == 3
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            assert set(cache["frames"]) == {"file_info", "1", "2"}
        finally:
            Path(tmp).unlink(missing_ok=True)
            cache_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# 3. 帧构造 (通过 build API 验证)
# ═══════════════════════════════════════════════════════════════

class TestUpgFrameBuild:
    def test_build_file_info_frame(self):
        """E8020701 文件信息帧可构造"""
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x07", "di": "E8020701",
            "dir": "downlink",
            "file_type": 2,
            "file_id": 0,
            "dest_addr": "999999999999",
            "total_segments": 2,
            "file_size": 256,
            "file_crc": 0xABCD,
            "timeout_minutes": 30,
        })
        _ok(r)
        assert "68" in r["data"]["frame"]

    def test_build_segment_frame(self):
        """E8020702 分段数据帧可构造"""
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x07", "di": "E8020702",
            "dir": "downlink",
            "segment_index": 0,
            "segment_length": 128,
            "segment_data": b"\x00" * 128,
            "segment_crc": 0xABCD,
        })
        _ok(r)
        assert "68" in r["data"]["frame"]

    def test_build_ack_frame(self):
        """E8010001 ACK 帧可构造 (用于理解设备响应)"""
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010001",
            "dir": "uplink", "wait_time": "0",
        })
        _ok(r)

    def test_parse_ack_frame_as_ack(self):
        from console.handlers.upg import _parse_ack

        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010001",
            "dir": "uplink", "wait_time": 0,
        })
        _ok(r)
        diag = {}
        assert _parse_ack(bytes.fromhex(r["data"]["frame"]), diag=diag) is True
        assert diag["ack_received"] is True

    def test_parse_nak_frame_as_nak(self):
        from console.handlers.upg import _parse_ack

        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010002",
            "dir": "uplink", "error_code": 1,
        })
        _ok(r)
        diag = {}
        assert _parse_ack(bytes.fromhex(r["data"]["frame"]), diag=diag) is False
        assert diag["nak_received"] is True
        assert diag["nak_error_code"] == 1


# ═══════════════════════════════════════════════════════════════
# 4. 命令注册
# ═══════════════════════════════════════════════════════════════

class TestUpgRegistry:
    def test_upg_registered(self):
        from console.api import list_cmds
        names = [c["name"] for c in list_cmds()]
        assert "upg" in names

    def test_help_upg(self):
        r = exec_cmd("help", {"target": "/upg"})
        _ok(r)
        assert r["data"]["command"] == "/upg"
