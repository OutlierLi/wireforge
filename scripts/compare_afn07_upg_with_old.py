#!/usr/bin/env python3
"""对比 Wireforge 与旧项目 AFN07 /upg 构帧是否字节级一致。

用法:
  python3 scripts/compare_afn07_upg_with_old.py [--file firmware.bin] [--segment-size 256]

旧项目路径默认: ../protocol-parsing-and-message-send-rcv
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_ROOT = ROOT.parent / "protocol-parsing-and-message-send-rcv"


def _norm(frame: str) -> str:
    return frame.replace(" ", "").upper()


def _compile_wireforge() -> None:
    from protocol_tool.compiler.pipeline import compile_protocol

    registry = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
    compile_protocol(str(registry), "csg_2016", output_dir=str(ROOT / "compiled"))


def _wireforge_build(di: str, fields: dict | None, *, seq: int) -> str:
    import protocol_tool.utils.logger as lg

    lg.log_build = lambda *a, **k: None
    lg.log_decode = lambda *a, **k: None

    from console.build_resolver import encode, resolve

    target = resolve({"proto": "csg", "afn": "07", "di": di, "dir": "downlink"})
    target.derived_fields["seq"] = seq & 0xFF
    return _norm(encode(target, fields or {}))


def _old_parser():
    if not OLD_ROOT.is_dir():
        raise SystemExit(f"old project not found: {OLD_ROOT}")
    sys.path.insert(0, str(OLD_ROOT))
    from protocol_parser.parser import ProtocolParser

    return ProtocolParser("csg", schema_root=OLD_ROOT / "database" / "protocols" / "csg_2016")


def _collect_pairs(
    *,
    firmware: Path,
    segment_size: int,
    dest: str,
    file_type: int,
    file_id: int,
    timeout_minutes: int,
) -> list[tuple[str, str, dict | None, dict | None]]:
    from console.handlers.file_transfer import (
        clear_file_info_payload,
        segment_file,
        segment_payload,
        start_file_info_payload,
    )

    package = segment_file(firmware, segment_size)
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
    start_wf = start_file_info_payload(
        file_type=file_type,
        file_id=file_id,
        dest_address=dest,
        package=package,
        timeout_minutes=timeout_minutes,
    )
    start_old = {
        "file_type": file_type,
        "file_id": file_id,
        "dest_address": dest,
        "total_segments": package.total_segments,
        "file_size": package.size,
        "file_crc16": package.crc16,
        "transfer_timeout_minutes": timeout_minutes,
    }

    pairs: list[tuple[str, str, dict | None, dict | None]] = [
        ("QUERY", "E8000703", {}, {}),
        ("CLEAR", "E8020701", clear_old, clear_wf),
        ("START", "E8020701", start_old, start_wf),
    ]
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
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="firmware bin (default: synthetic 512B)")
    parser.add_argument("--segment-size", type=int, default=256, choices=[128, 256, 512, 1024])
    parser.add_argument("--dest", default="999999999999")
    parser.add_argument("--file-type", type=int, default=1)
    parser.add_argument("--file-id", type=int, default=1)
    parser.add_argument("--timeout-min", type=int, default=30)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    _compile_wireforge()
    old = _old_parser()

    if args.file and args.file.exists():
        firmware = args.file
        cleanup = False
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
        tmp.write(bytes((i * 7 + 13) & 0xFF for i in range(512)))
        tmp.close()
        firmware = Path(tmp.name)
        cleanup = True

    pairs = _collect_pairs(
        firmware=firmware,
        segment_size=args.segment_size,
        dest=args.dest,
        file_type=args.file_type,
        file_id=args.file_id,
        timeout_minutes=args.timeout_min,
    )

    seq = 1
    mismatches = 0
    print(f"firmware={firmware} segment_size={args.segment_size} frames={len(pairs)}")
    print("-" * 72)
    for label, di, old_fields, wf_fields in pairs:
        old_hex = _norm(old.build_hex("07", di, old_fields or {}, seq=seq))
        wf_hex = _wireforge_build(di, wf_fields, seq=seq)
        ok = old_hex == wf_hex
        status = "OK" if ok else "MISMATCH"
        print(f"[{status}] {label:16} DI={di} seq={seq:3d}")
        if not ok:
            mismatches += 1
            print(f"  old: {old_hex}")
            print(f"  wf : {wf_hex}")
        seq = (seq + 1) & 0xFF

    if cleanup:
        firmware.unlink(missing_ok=True)

    print("-" * 72)
    if mismatches:
        print(f"FAILED: {mismatches} frame(s) differ")
        return 1
    print("PASSED: all frames byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
