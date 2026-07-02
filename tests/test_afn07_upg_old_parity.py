"""AFN07 /upg 构帧与旧项目 protocol-parsing-and-message-send-rcv 字节级一致。

对比范围：QUERY / CLEAR / START / 全部分段 E8020702。
旧项目权威实现：script_console/dsl.py::_cmd_upg + ProtocolParser.build_hex。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

_OLD_ROOT = _project_root.parent / "protocol-parsing-and-message-send-rcv"


def _norm_hex(frame: str) -> str:
    return frame.replace(" ", "").upper()


def _wireforge_build(di: str, fields: dict | None, *, seq: int) -> str:
    import protocol_tool.utils.logger as lg

    lg.log_build = lambda *a, **k: None
    lg.log_decode = lambda *a, **k: None

    from console.build_resolver import encode, resolve

    target = resolve(
        {
            "proto": "csg",
            "afn": "07",
            "di": di,
            "dir": "downlink",
            "seq": seq,
        }
    )
    target.derived_fields["seq"] = seq & 0xFF
    return _norm_hex(encode(target, fields or {}))


def _old_parser():
    if not _OLD_ROOT.is_dir():
        return None
    old_db = _OLD_ROOT / "database"
    if not (old_db / "protocols" / "csg_2016").is_dir():
        return None
    sys.path.insert(0, str(_OLD_ROOT))
    from protocol_parser.parser import ProtocolParser

    return ProtocolParser("csg", schema_root=old_db / "protocols" / "csg_2016")


def _old_build(parser, di: str, fields: dict | None, *, seq: int) -> str:
    return _norm_hex(parser.build_hex("07", di, fields or {}, seq=seq))


@unittest.skipUnless(_OLD_ROOT.is_dir(), "old project not found beside wireforge")
class Afn07UpgOldParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from protocol_tool.compiler.pipeline import compile_protocol

        registry = _project_root / "protocol_tool" / "protocols" / "registry.yaml"
        compile_protocol(str(registry), "csg_2016", output_dir=str(_project_root / "compiled"))
        cls.parser = _old_parser()
        if cls.parser is None:
            raise unittest.SkipTest("old project CSG schema not found")

    def _assert_pair(self, label: str, di: str, old_fields: dict | None, wf_fields: dict | None, *, seq: int) -> None:
        old_hex = _old_build(self.parser, di, old_fields, seq=seq)
        wf_hex = _wireforge_build(di, wf_fields, seq=seq)
        self.assertEqual(wf_hex, old_hex, f"{label} DI={di} seq={seq}\nold={old_hex}\n wf={wf_hex}")

    def test_query_file_info_empty(self) -> None:
        self._assert_pair("QUERY", "E8000703", {}, {}, seq=1)

    def test_clear_file_info(self) -> None:
        dest = "999999999999"
        old = {
            "file_type": 0,
            "file_id": 0,
            "dest_address": dest,
            "total_segments": 0,
            "file_size": 0,
            "file_crc16": 0,
            "transfer_timeout_minutes": 0,
        }
        wf = {
            "file_type": 0,
            "file_id": 0,
            "dest_addr": dest,
            "total_segments": 0,
            "file_size": 0,
            "file_crc": 0,
            "timeout_minutes": 0,
        }
        self._assert_pair("CLEAR", "E8020701", old, wf, seq=1)

    def test_start_file_info(self) -> None:
        from console.handlers.file_transfer import segment_file

        data = bytes(i & 0xFF for i in range(300))
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(data)
            path = Path(tmp.name)
        try:
            package = segment_file(path, 128)
            dest = "999999999999"
            old = {
                "file_type": 1,
                "file_id": 1,
                "dest_address": dest,
                "total_segments": package.total_segments,
                "file_size": package.size,
                "file_crc16": package.crc16,
                "transfer_timeout_minutes": 30,
            }
            wf = {
                "file_type": 1,
                "file_id": 1,
                "dest_addr": dest,
                "total_segments": package.total_segments,
                "file_size": package.size,
                "file_crc": package.crc16,
                "timeout_minutes": 30,
            }
            self._assert_pair("START", "E8020701", old, wf, seq=2)
        finally:
            path.unlink(missing_ok=True)

    def test_all_segments_for_sample_firmware(self) -> None:
        from console.handlers.file_transfer import segment_file

        data = bytes(i & 0xFF for i in range(300))
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(data)
            path = Path(tmp.name)
        try:
            package = segment_file(path, 128)
            self.assertEqual(package.total_segments, 3)
            seq = 10
            for segment in package.segments:
                old = {
                    "segment_no": segment.number,
                    "segment_content": {"raw": segment.data.hex().upper()},
                    "segment_crc16": segment.crc16,
                }
                wf = {
                    "segment_index": segment.number,
                    "segment_length": segment.length,
                    "segment_data": segment.data,
                    "segment_crc": segment.crc16,
                }
                self._assert_pair(
                    f"SEGMENT[{segment.number}]",
                    "E8020702",
                    old,
                    wf,
                    seq=seq,
                )
                seq = (seq + 1) & 0xFF
        finally:
            path.unlink(missing_ok=True)

    def test_full_upg_frame_sequence(self) -> None:
        """模拟 dsl _cmd_upg 完整下行序列：QUERY → CLEAR → START → 各段。"""
        from console.handlers.file_transfer import (
            clear_file_info_payload,
            segment_file,
            segment_payload,
            start_file_info_payload,
        )

        data = bytes((index * 7 + 13) & 0xFF for index in range(512))
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(data)
            path = Path(tmp.name)
        try:
            package = segment_file(path, 256)
            dest = "012400038813"
            seq = 1

            pairs: list[tuple[str, str, dict | None, dict | None]] = [
                ("QUERY", "E8000703", {}, {}),
                ("CLEAR", "E8020701", None, None),
                ("START", "E8020701", None, None),
            ]

            clear_wf = clear_file_info_payload(dest)
            clear_old = {
                "file_type": 0,
                "file_id": 0,
                "dest_address": dest,
                "total_segments": 0,
                "file_size": 0,
                "file_crc16": 0,
                "transfer_timeout_minutes": 0,
            }
            pairs[1] = ("CLEAR", "E8020701", clear_old, clear_wf)

            start_wf = start_file_info_payload(
                file_type=2,
                file_id=3,
                dest_address=dest,
                package=package,
                timeout_minutes=45,
            )
            start_old = {
                "file_type": 2,
                "file_id": 3,
                "dest_address": dest,
                "total_segments": package.total_segments,
                "file_size": package.size,
                "file_crc16": package.crc16,
                "transfer_timeout_minutes": 45,
            }
            pairs[2] = ("START", "E8020701", start_old, start_wf)

            for segment in package.segments:
                pairs.append(
                    (
                        f"SEGMENT[{segment.number}]",
                        "E8020702",
                        {
                            "segment_no": segment.number,
                            "segment_content": {"raw": segment.data.hex().upper()},
                            "segment_crc16": segment.crc16,
                        },
                        segment_payload(segment),
                    )
                )

            for label, di, old_fields, wf_fields in pairs:
                self._assert_pair(label, di, old_fields, wf_fields, seq=seq)
                seq = (seq + 1) & 0xFF
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
