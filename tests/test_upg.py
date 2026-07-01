"""/upg 全量测试 — 分段、CRC、帧构造、参数校验、噪声过滤、续传。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd
from console.arg_utils import strip_nested_quotes
from console.handlers.file_transfer import (
    crc16_ccitt,
    normalize_file_path,
    parse_duration,
    segment_file,
)
from console.runtime import parse_command_text


def _ok(r, msg=""):
    assert r["status"] == "success", f"expected success: {msg} | got: {r}"


def _fail(r, msg=""):
    assert r["status"] != "success", f"expected fail: {msg} | got: {r}"


def _close_all_serial() -> None:
    from wireforge_serial.api import list_connected_names

    for name in list(list_connected_names()):
        exec_cmd("serial", {"sub": "close", "to": name})


class UpgradeResponderTransport:
    """Mock transport that ACKs file transfer frames and optionally returns query/progress."""

    def __init__(
        self,
        expected_segments: int,
        *,
        file_size: int = 0,
        file_crc: int = 0,
        resume_from: int = 0,
        resume_match: bool = True,
        noise_before_ack: bool = False,
        progress_sequence: list[int] | None = None,
    ) -> None:
        self.expected_segments = expected_segments
        self.file_size = file_size
        self.file_crc = file_crc
        self.resume_from = resume_from
        self.resume_match = resume_match
        self.noise_before_ack = noise_before_ack
        self.progress_sequence = list(progress_sequence or [])
        self.segment_count = 0
        self.sent_count = 0
        self.read_timeouts: list[float] = []
        self._queue: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.sent_count += 1
        r = exec_cmd("decode", {"proto": "csg", "hex": data.hex(" ")})
        if r.get("status") != "success":
            raise AssertionError(f"failed to decode TX: {r}")
        values = r["data"]["values"]
        di = _extract_di(values)

        if di == "E8000703":
            if self.resume_match and self.resume_from > 0:
                payload = {
                    "file_type": 1,
                    "file_id": 1,
                    "dest_addr": "999999999999",
                    "total_segments": self.expected_segments,
                    "file_size": self.file_size,
                    "file_crc": self.file_crc,
                    "received_segments": self.resume_from,
                }
            else:
                payload = {
                    "file_type": 9,
                    "file_id": 9,
                    "dest_addr": "000000000000",
                    "total_segments": 1,
                    "file_size": 1,
                    "file_crc": 0,
                    "received_segments": 0,
                }
            self._queue.append(_build_uplink("07", "E8000703", payload))
        elif di == "E8000704":
            progress = self.progress_sequence.pop(0) if self.progress_sequence else 0
            self._queue.append(_build_uplink("07", "E8000704", {
                "progress": progress,
                "unfinished_file_id": 0,
                "failed_node_count": 0,
            }))
        elif di in {"E8020701", "E8020702"}:
            if di == "E8020702":
                self.segment_count += 1
            ack = _build_uplink("00", "E8010001", {"wait_time": 0})
            if self.noise_before_ack:
                # Unrelated valid CSG frame (AFN06 request time) queued before ACK.
                noise = exec_cmd("build", {
                    "proto": "csg", "afn": "0x06", "di": "E8060601", "dir": "downlink",
                })
                if noise.get("status") == "success":
                    self._queue.append(bytes.fromhex(noise["data"]["frame"]))
            self._queue.append(ack)
        else:
            raise AssertionError(f"unexpected DI: {di}")
        return len(data)

    def read_response(self, timeout: float, *, idle_timeout: float = 0.05) -> bytes:
        self.read_timeouts.append(timeout)
        if self._queue:
            return self._queue.pop(0)
        return b""

    def close(self) -> None:
        self.closed = True


def _extract_di(values: dict) -> str:
    for key in ("data_content", "user_data"):
        container = values.get(key) or {}
        if "di" in container:
            raw = str(container["di"])
            return "".join(raw.replace("0x", "").replace("0X", "").split()).upper()
    return ""


def _build_uplink(afn: str, di: str, fields: dict, *, direction: str = "uplink") -> bytes:
    payload = {
        "proto": "csg",
        "afn": afn if afn.startswith("0x") else f"0x{afn}",
        "di": di,
        "dir": direction,
        **fields,
    }
    r = exec_cmd("build", payload)
    assert r["status"] == "success", r
    return bytes.fromhex(r["data"]["frame"])


class TestFileTransferHelpers(unittest.TestCase):
    def test_crc16_ccitt_known(self) -> None:
        self.assertEqual(crc16_ccitt(bytes(range(20))), 0xACCC)

    def test_segment_size_must_match_protocol_allowed_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "fw.bin"
            source.write_bytes(bytes(range(20)))
            with self.assertRaisesRegex(Exception, "128/256/512/1024"):
                segment_file(source, 8)

    def test_strip_nested_quotes(self) -> None:
        self.assertEqual(strip_nested_quotes('"""fw.bin"""'), "fw.bin")
        self.assertEqual(strip_nested_quotes("'\"/tmp/fw.bin\"'"), "/tmp/fw.bin")

    def test_normalize_file_path_nested_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            fw.write_bytes(b"abc")
            resolved = normalize_file_path(f'"""{fw}"""', root=_project_root)
            self.assertEqual(resolved, fw.resolve())

    def test_parse_duration(self) -> None:
        self.assertEqual(parse_duration("30s"), 30.0)
        self.assertEqual(parse_duration("500ms"), 0.5)
        self.assertEqual(parse_duration(5), 5.0)


class TestUpgParams(unittest.TestCase):
    def test_missing_file(self) -> None:
        r = exec_cmd("upg", {})
        _fail(r)
        assert "file" in str(r.get("input_schema", []))

    def test_file_not_found(self) -> None:
        r = exec_cmd("upg", {"file": "nonexistent.bin"})
        _fail(r)
        assert "not found" in r.get("error", "")

    def test_invalid_segment_size(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name
        try:
            r = exec_cmd("upg", {"file": tmp, "segment-size": "999"})
            _fail(r)
            assert "segment-size" in r.get("error", "").lower()
        finally:
            Path(tmp).unlink()

    def test_no_serial_connection(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name
        try:
            _close_all_serial()
            r = exec_cmd("upg", {"file": tmp, "segment-size": "128", "no-resume": True, "to": "cco"})
            _fail(r)
            assert "not connected" in r.get("error", "").lower()
            assert "to=cco" in r.get("error", "")
        finally:
            Path(tmp).unlink()

    def test_no_serial_connection_without_to(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name
        try:
            _close_all_serial()
            r = exec_cmd("upg", {"file": tmp, "segment-size": "128", "no-resume": True})
            _fail(r)
            assert "no serial connected" in r.get("error", "").lower()
        finally:
            Path(tmp).unlink()

    def test_multiple_connections_require_to(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name
        try:
            _close_all_serial()
            exec_cmd("serial", {"sub": "connect", "to": "cco", "port": "mock://loop"})
            exec_cmd("serial", {"sub": "connect", "to": "sta1", "port": "mock://loop"})
            r = exec_cmd("upg", {"file": tmp, "segment-size": "128", "no-resume": True})
            _fail(r)
            assert "multiple serial connections" in r.get("error", "")
            assert "cco" in r.get("error", "")
            assert "sta1" in r.get("error", "")
        finally:
            Path(tmp).unlink()
            _close_all_serial()

    def test_auto_detect_single_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            fw.write_bytes(bytes(range(64)))
            transport = UpgradeResponderTransport(expected_segments=1)
            _close_all_serial()
            exec_cmd("serial", {"sub": "connect", "to": "cco", "port": "mock://loop"})

            def fake_get(name=None):
                if name == "cco":
                    return transport
                return None

            with patch("console.handlers.upg.get_connection", side_effect=fake_get):
                r = exec_cmd("upg", {
                    "file": str(fw),
                    "segment-size": 128,
                    "no-cache": True,
                    "no-resume": True,
                })
            _ok(r)
            self.assertEqual(r["data"]["to"], "cco")
            _close_all_serial()

    def test_unsupported_proto(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00" * 100)
            tmp = f.name
        try:
            r = exec_cmd("upg", {"file": tmp, "proto": "dlt645", "build-only": True})
            _fail(r)
            assert "unsupported proto" in r.get("error", "").lower()
        finally:
            Path(tmp).unlink()

    def test_proto_defaults_to_csg(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(bytes(range(64)))
            tmp = f.name
        try:
            r = exec_cmd("upg", {"file": tmp, "build-only": True, "no-cache": True})
            _ok(r)
            assert r["data"]["proto"] == "csg"
        finally:
            Path(tmp).unlink(missing_ok=True)
            Path(tmp + ".upg_cache").unlink(missing_ok=True)

    def test_build_only_writes_v2_cache(self) -> None:
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
            assert r["data"]["frames_validated"] == 3
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache["version"], 2)
            self.assertEqual(cache["crc_algo"], "ccitt")
            self.assertEqual(len(cache["segments"]), 2)
        finally:
            Path(tmp).unlink(missing_ok=True)
            cache_path.unlink(missing_ok=True)


class TestUpgFrameBuild(unittest.TestCase):
    def test_build_file_info_frame(self) -> None:
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x07", "di": "E8020701",
            "dir": "downlink",
            "file_type": 1,
            "file_id": 1,
            "dest_addr": "999999999999",
            "total_segments": 2,
            "file_size": 256,
            "file_crc": 0xABCD,
            "timeout_minutes": 30,
        })
        _ok(r)
        assert "68" in r["data"]["frame"]

    def test_parse_ack_frame(self) -> None:
        from console.handlers.file_transfer import ack_from_decoded

        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x00", "di": "E8010001",
            "dir": "uplink", "wait_time": 0,
        })
        _ok(r)
        decoded = exec_cmd("decode", {"proto": "csg", "hex": r["data"]["frame"]})
        ack = ack_from_decoded(decoded["data"])
        self.assertTrue(ack.ok)


class TestUpgTransferFlow(unittest.TestCase):
    def _run_upg(self, fw_path: Path, transport: UpgradeResponderTransport, **extra) -> dict:
        _close_all_serial()
        exec_cmd("serial", {"sub": "connect", "to": "dev1", "port": "mock://loop"})
        with patch("console.handlers.upg.get_connection", return_value=transport):
            return exec_cmd("upg", {
                "file": str(fw_path),
                "to": "dev1",
                "segment-size": 128,
                "no-resume": True,
                "no-cache": True,
                **extra,
            })

    def test_upg_sends_segments_with_noise_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            fw.write_bytes(bytes(index % 256 for index in range(260)))
            transport = UpgradeResponderTransport(expected_segments=3, noise_before_ack=True)
            r = self._run_upg(fw, transport, finish="none")
            _ok(r)
            self.assertEqual(transport.segment_count, 3)

    def test_upg_resume_skips_start_when_file_info_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            data = bytes(index % 256 for index in range(260))
            fw.write_bytes(data)
            pkg = segment_file(fw, 128)
            transport = UpgradeResponderTransport(
                expected_segments=3,
                file_size=pkg.size,
                file_crc=pkg.crc16,
                resume_from=2,
                resume_match=True,
            )
            with patch("console.handlers.upg.get_connection", return_value=transport):
                r = exec_cmd("upg", {
                    "file": str(fw),
                    "to": "dev1",
                    "segment-size": 128,
                    "no-cache": True,
                    "resume": True,
                    "clear": "never",
                })
            _ok(r)
            self.assertEqual(r["data"].get("resumed_from"), 2)
            self.assertEqual(transport.segment_count, 1)

    def test_upg_clear_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            fw.write_bytes(bytes(index % 256 for index in range(128)))
            transport = UpgradeResponderTransport(
                expected_segments=1,
                resume_match=False,
            )
            with patch("console.handlers.upg.get_connection", return_value=transport):
                r = exec_cmd("upg", {
                    "file": str(fw),
                    "to": "dev1",
                    "segment-size": 128,
                    "no-cache": True,
                    "resume": True,
                    "clear": "auto",
                })
            _ok(r)
            self.assertGreaterEqual(transport.sent_count, 3)

    def test_upg_finish_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fw = Path(temp_dir) / "fw.bin"
            fw.write_bytes(bytes(range(64)))
            transport = UpgradeResponderTransport(
                expected_segments=1,
                progress_sequence=[1, 0],
            )
            with patch("console.handlers.upg.get_connection", return_value=transport):
                r = exec_cmd("upg", {
                    "file": str(fw),
                    "to": "dev1",
                    "segment-size": 128,
                    "no-cache": True,
                    "no-resume": True,
                    "finish": "progress",
                    "finish-timeout": "5s",
                })
            _ok(r)
            self.assertEqual(r["data"]["finish"]["mode"], "progress")


class TestUpgRegistry(unittest.TestCase):
    def test_upg_registered(self) -> None:
        from console.api import list_cmds
        names = [c["name"] for c in list_cmds()]
        self.assertIn("upg", names)

    def test_help_upg(self) -> None:
        r = exec_cmd("help", {"target": "/upg"})
        _ok(r)
        self.assertEqual(r["data"]["command"], "/upg")

    def test_parse_command_text_nested_quotes(self) -> None:
        cmd, args = parse_command_text('/upg --file=""/tmp/fw.bin"" --build-only')
        self.assertEqual(cmd, "upg")
        self.assertEqual(strip_nested_quotes(args["file"]), "/tmp/fw.bin")


if __name__ == "__main__":
    unittest.main()
