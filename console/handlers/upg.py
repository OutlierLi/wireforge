"""/upg 命令处理器 — CSG AFN=07 文件传输/固件升级。

流程: 读取固件 → 构建 v2 段缓存(.upg_cache) → 清除/续传 → 启动传输 → 逐段 live build 发送
→ ACK/NAK（噪声过滤）→ 可选进度收尾。

参数:
  --file              固件路径（支持多层引号；相对路径会搜索 database/bin）
  --segment-size      128/256/512/1024，默认 1024
  --file-type         文件性质，默认 1
  --file-id           文件 ID，默认 1
  --dest              目的地址，默认 999999999999
  --timeout-min       传输超时分钟，默认 30
  --ack-timeout       普通段 ACK 超时（兼容 --timeout），默认 5s
  --final-ack-timeout 最后一段 ACK 超时，默认 30s
  --retries           每段重试次数，默认 3
  --interval          帧间间隔，默认 0
  --ack-wait          ignore/respect，默认 ignore
  --resume / --no-resume  断点续传，默认开启
  --clear             auto/always/never，默认 auto
  --finish            none/progress/report，默认 none
  --finish-timeout    progress 轮询总超时，默认 60s
  --seq               起始 SEQ，默认 1
  --to                串口连接名（可选；仅一个已连接串口时自动选用）
  --proto             协议，默认 csg（当前仅支持 csg / csg2016）
  --no-cache          跳过缓存
  --build-only        仅构建缓存并验证可 build
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from console.api import exec_cmd
from console.handlers.file_transfer import (
    CACHE_CRC_ALGO,
    CACHE_VERSION,
    AckResult,
    FileTransferError,
    ack_from_decoded,
    cache_is_valid,
    clear_file_info_payload,
    parse_duration,
    payload_from_decoded,
    parsed_di,
    same_file_info,
    segment_file,
    segment_payload,
    start_file_info_payload,
    normalize_file_path,
)
from console.handlers.frame_splitter import split_frames
from console.response import fail, missing_param, ok
from protocol_tool.utils.logger import log_serial
from wireforge_serial.api import get_connection, list_connected_names

ROOT = Path(__file__).resolve().parent.parent.parent

_PROTO_ALIASES = {
    "csg": "csg",
    "csg2016": "csg",
    "csg_2016": "csg",
}


def _normalize_proto(raw: str | None) -> str:
    proto = str(raw or "csg").strip().lower()
    normalized = _PROTO_ALIASES.get(proto)
    if normalized is None:
        raise FileTransferError(
            f"unsupported proto: {proto}; currently only csg (aliases: csg2016, csg_2016)"
        )
    return normalized


def _resolve_connection(args: dict[str, Any]) -> tuple[str, Any]:
    """Resolve serial connection by --to, or auto-select when exactly one is connected."""
    explicit = args.get("to")
    if explicit:
        name = str(explicit)
        transport = get_connection(name)
        if not transport:
            raise FileTransferError(
                f"serial not connected (to={name}). "
                f"use /serial connect --name {name} --port <port> first"
            )
        return name, transport

    connected = list_connected_names()
    if not connected:
        raise FileTransferError(
            "no serial connected. use /serial connect --name <id> --port <port> first"
        )
    if len(connected) > 1:
        joined = ", ".join(connected)
        raise FileTransferError(
            f"multiple serial connections active ({joined}); specify --to=<name>"
        )

    name = connected[0]
    transport = get_connection(name)
    if not transport:
        raise FileTransferError(f"serial not connected (to={name})")
    return name, transport


def handle(args: dict[str, Any]) -> dict:
    raw_file = args.get("file") or args.get("bin")
    if not raw_file:
        return missing_param("file", "str", examples=["database/bin/firmware.bin", '"/path/with spaces/fw.bin"'])

    try:
        fp = normalize_file_path(str(raw_file), root=ROOT)
    except FileTransferError as exc:
        return fail(str(exc))

    if not fp.exists():
        return fail(f"file not found: {fp}")

    try:
        params = _parse_transfer_params(args)
        package = segment_file(fp, params["segment_size"])
    except FileTransferError as exc:
        return fail(str(exc))
    except ValueError as exc:
        return fail(str(exc))

    file_hash = hashlib.md5(package.data).hexdigest()[:8]
    cache_path = fp.with_suffix(fp.suffix + ".upg_cache")
    use_cache = not args.get("no-cache")

    cache_params = {
        "proto": params["proto"],
        "file_type": params["file_type"],
        "file_id": params["file_id"],
        "dest": params["dest"],
        "timeout_minutes": params["timeout_minutes"],
    }

    cache: dict[str, Any] | None = None
    if use_cache and cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if cache_is_valid(
                loaded,
                file_hash=file_hash,
                segment_size=params["segment_size"],
                params=cache_params,
            ):
                cache = loaded
        except (json.JSONDecodeError, OSError):
            use_cache = False

    if cache is None:
        try:
            cache = _build_cache_v2(package, file_hash, cache_params)
        except RuntimeError as exc:
            return fail(f"failed to build upgrade cache: {exc}")
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        use_cache = False

    results: dict[str, Any] = {
        "file": str(fp.name),
        "file_path": str(fp),
        "file_size": package.size,
        "total_segments": package.total_segments,
        "segment_size": params["segment_size"],
        "file_crc": f"0x{package.crc16:04X}",
        "cached": use_cache,
        "cache_path": str(cache_path),
        "proto": params["proto"],
    }

    if params["build_only"]:
        results["frames_validated"] = package.total_segments + 1
        return ok(results)

    try:
        conn_name, transport = _resolve_connection(args)
    except FileTransferError as exc:
        return fail(str(exc))

    from wireforge_serial.api import bind_rx_display, write_with_tx_display

    bind_rx_display(transport, conn_name)

    results["to"] = conn_name

    log_serial("upg_start", port="", data={
        "to": conn_name,
        "proto": params["proto"],
        "file": str(fp.name),
        "size": package.size,
        "segments": package.total_segments,
        "segment_size": params["segment_size"],
        "cached": use_cache,
    })

    seq = params["seq"] & 0xFF

    def next_seq() -> int:
        nonlocal seq
        value = seq
        seq = (seq + 1) & 0xFF
        return value

    proto = params["proto"]

    def build_frame(di: str, fields: dict[str, Any] | None = None) -> bytes:
        payload = {
            "proto": proto,
            "afn": "0x07",
            "di": di,
            "dir": "downlink",
            "seq": next_seq(),
        }
        if fields:
            payload.update(fields)
        r = exec_cmd("build", payload)
        if r.get("status") != "success" or not r.get("data", {}).get("frame"):
            raise RuntimeError(r.get("error") or f"build failed for DI={di}")
        return bytes.fromhex(r["data"]["frame"])

    def decode_frame(frame: bytes) -> dict[str, Any] | None:
        r = exec_cmd("decode", {"proto": proto, "hex": frame.hex(" ")})
        if r.get("status") == "success":
            return r.get("data", {})
        return None

    def send_receive(
        label: str,
        frame: bytes,
        timeout: float,
        *,
        retry_count: int | None = None,
        accept: Callable[[dict[str, Any]], bool] | None = None,
        expected: str = "response",
        diag: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = (params["retries"] if retry_count is None else retry_count) + 1
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            try:
                write_with_tx_display(transport, conn_name, frame)
                if diag is not None:
                    diag["last_send_hex"] = frame.hex(" ")
                deadline = time.monotonic() + max(timeout, 0.0)
                while time.monotonic() < deadline:
                    remaining = max(0.0, deadline - time.monotonic())
                    rx = transport.read_response(remaining)
                    if not rx:
                        break
                    frames, _ = split_frames(rx)
                    if not frames:
                        last_error = f"{label} ignored non-CSG bytes while waiting for {expected}"
                        continue
                    for index, raw_frame in enumerate(frames):
                        decoded = decode_frame(raw_frame)
                        if decoded is None:
                            last_error = f"{label} ignored decode error while waiting for {expected}"
                            continue
                        if accept is None or accept(decoded):
                            return decoded
                        last_error = (
                            f"{label} ignored DI={parsed_di(decoded) or '<unknown>'} "
                            f"while waiting for {expected}"
                        )
                if last_error is None or "ignored" in (last_error or ""):
                    last_error = f"{label} waiting for {expected} timeout"
                if attempt < attempts:
                    continue
                if diag is not None:
                    diag["last_error"] = last_error
                raise RuntimeError(last_error)
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = f"{label} transport error: {type(exc).__name__}: {exc}"
                if attempt >= attempts:
                    if diag is not None:
                        diag["last_error"] = last_error
                    raise RuntimeError(last_error) from exc
            finally:
                if params["interval"] > 0:
                    time.sleep(params["interval"])
        if diag is not None:
            diag["last_error"] = last_error or "unknown"
        raise RuntimeError(last_error or f"{label} failed")

    def is_ack_or_nak(decoded: dict[str, Any]) -> bool:
        try:
            ack_from_decoded(decoded)
            return True
        except FileTransferError:
            return False

    def expect_ack(label: str, frame: bytes, *, timeout: float | None = None, diag: dict[str, Any] | None = None) -> AckResult:
        decoded = send_receive(
            label,
            frame,
            params["ack_timeout"] if timeout is None else timeout,
            accept=is_ack_or_nak,
            expected="ACK/NAK",
            diag=diag,
        )
        ack = ack_from_decoded(decoded)
        if not ack.ok:
            raise RuntimeError(f"{label} denied: {ack.error_message}")
        if ack.wait_time > 0:
            if params["ack_wait"] == "respect":
                time.sleep(ack.wait_time)
        return ack

    def receive_di(
        label: str,
        frame: bytes,
        timeout: float,
        di: str,
        *,
        retry_count: int | None = None,
    ) -> dict[str, Any]:
        expected_di = di.upper()
        return send_receive(
            label,
            frame,
            timeout,
            retry_count=retry_count,
            accept=lambda decoded: parsed_di(decoded) == expected_di,
            expected=f"DI={expected_di}",
        )

    start_time = time.monotonic()
    start_segment = 0

    try:
        if params["clear_mode"] == "always":
            clear_frame = build_frame("E8020701", clear_file_info_payload(params["dest"]))
            expect_ack("CLEAR", clear_frame)
        elif params["resume_enabled"]:
            try:
                query_frame = build_frame("E8000703")
                decoded = receive_di(
                    "QUERY_FILE_INFO",
                    query_frame,
                    params["ack_timeout"],
                    "E8000703",
                    retry_count=0,
                )
                file_info = payload_from_decoded(decoded)
            except RuntimeError as exc:
                file_info = None
                results["resume_note"] = str(exc)
            else:
                if file_info and same_file_info(
                    file_info,
                    file_type=params["file_type"],
                    file_id=params["file_id"],
                    dest_address=params["dest"],
                    package=package,
                ):
                    start_segment = min(int(file_info.get("received_segments", 0)), package.total_segments)
                    if start_segment > 0:
                        results["resumed_from"] = start_segment
                elif file_info and params["clear_mode"] == "auto":
                    clear_frame = build_frame("E8020701", clear_file_info_payload(params["dest"]))
                    expect_ack("CLEAR", clear_frame)

        if start_segment == 0:
            start_frame = build_frame(
                "E8020701",
                start_file_info_payload(
                    file_type=params["file_type"],
                    file_id=params["file_id"],
                    dest_address=params["dest"],
                    package=package,
                    timeout_minutes=params["timeout_minutes"],
                ),
            )
            expect_ack("START", start_frame)
            results["file_info_ack"] = True

        segments_to_send = package.segments[start_segment:]
        last_segment_number = segments_to_send[-1].number if segments_to_send else None
        sent = 0

        for segment in segments_to_send:
            seg_frame = build_frame("E8020702", segment_payload(segment))
            seg_timeout = (
                params["final_ack_timeout"]
                if segment.number == last_segment_number
                else params["ack_timeout"]
            )
            expect_ack(f"SEGMENT[{segment.number}]", seg_frame, timeout=seg_timeout)
            sent += 1
            transferred = start_segment + sent
            remaining = max(package.total_segments - transferred, 0)
            percent = 100.0 if package.total_segments == 0 else transferred * 100.0 / package.total_segments
            _write_progress_bar(transferred, package.total_segments, remaining, percent)

        finish_result: dict[str, Any] | None = None
        if params["finish_mode"] == "progress":
            finish_result = _wait_progress_finish(build_frame, receive_di, params["finish_timeout"])
        elif params["finish_mode"] == "report":
            finish_result = {"mode": "report", "skipped": True}
        elif params["finish_mode"] != "none":
            return fail(f"unsupported finish mode: {params['finish_mode']}")

    except RuntimeError as exc:
        results["duration_seconds"] = round(time.monotonic() - start_time, 1)
        _finish_progress_bar()
        return fail(str(exc), detail=results)

    elapsed = time.monotonic() - start_time
    results["sent_segments"] = sent
    results["duration_seconds"] = round(elapsed, 1)
    results["success"] = True
    results["finish"] = finish_result
    _finish_progress_bar()

    log_serial("upg_complete", port="", data=results)
    return ok(results)


def _parse_transfer_params(args: dict[str, Any]) -> dict[str, Any]:
    segment_size = int(args.get("segment-size", args.get("segment_size", 1024)))
    ack_timeout_raw = args.get("ack-timeout", args.get("timeout", "5"))
    final_ack_raw = args.get("final-ack-timeout", args.get("last-timeout", "30"))
    finish_timeout_raw = args.get("finish-timeout", args.get("report-timeout", "60"))
    interval_raw = args.get("interval", "0")

    resume_enabled = True
    if args.get("no-resume") or args.get("resume") is False:
        resume_enabled = False
    elif args.get("resume") is True or str(args.get("resume", "true")).lower() in {"true", "1", "yes"}:
        resume_enabled = True

    ack_wait = str(args.get("ack-wait", args.get("ack_wait", "ignore"))).lower()
    if ack_wait not in {"ignore", "respect"}:
        raise FileTransferError("--ack-wait must be ignore or respect")

    clear_mode = str(args.get("clear", "auto")).lower()
    if clear_mode not in {"auto", "always", "never"}:
        raise FileTransferError("--clear must be auto, always or never")

    finish_mode = str(args.get("finish", "none")).lower()
    if finish_mode not in {"none", "progress", "report"}:
        raise FileTransferError("--finish must be none, progress or report")

    return {
        "proto": _normalize_proto(str(args.get("proto", args.get("protocol", "csg")))),
        "segment_size": segment_size,
        "file_type": int(args.get("file-type", args.get("file_type", 1))),
        "file_id": int(args.get("file-id", args.get("file_id", 1))),
        "dest": str(args.get("dest", args.get("dst", args.get("dst-address", "999999999999")))),
        "timeout_minutes": int(args.get("timeout-min", args.get("timeout_minutes", 30))),
        "ack_timeout": parse_duration(ack_timeout_raw),
        "final_ack_timeout": parse_duration(final_ack_raw),
        "finish_timeout": parse_duration(finish_timeout_raw),
        "interval": parse_duration(interval_raw),
        "retries": int(args.get("retries", 3)),
        "ack_wait": ack_wait,
        "resume_enabled": resume_enabled,
        "clear_mode": clear_mode,
        "finish_mode": finish_mode,
        "seq": int(args.get("seq", 1)),
        "build_only": bool(args.get("build-only")),
    }


def _build_cache_v2(
    package: SegmentedFile,
    file_hash: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    proto = params["proto"]
    seq = 1
    errors: list[str] = []

    def validate_build(di: str, fields: dict[str, Any] | None = None) -> None:
        nonlocal seq
        payload = {
            "proto": proto,
            "afn": "0x07",
            "di": di,
            "dir": "downlink",
            "seq": seq,
        }
        if fields:
            payload.update(fields)
        seq = (seq + 1) & 0xFF
        r = exec_cmd("build", payload)
        if r.get("status") != "success" or not r.get("data", {}).get("frame"):
            errors.append(f"{di}: {r.get('error') or r}")

    validate_build(
        "E8020701",
        start_file_info_payload(
            file_type=params["file_type"],
            file_id=params["file_id"],
            dest_address=params["dest"],
            package=package,
            timeout_minutes=params["timeout_minutes"],
        ),
    )
    for segment in package.segments:
        validate_build("E8020702", segment_payload(segment))

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "version": CACHE_VERSION,
        "crc_algo": CACHE_CRC_ALGO,
        "file_name": package.path.name,
        "file_hash": file_hash,
        "file_size": package.size,
        "segment_size": package.segment_size,
        "total_segments": package.total_segments,
        "file_crc": f"0x{package.crc16:04X}",
        "params": params,
        "segments": [
            {
                "number": segment.number,
                "data_hex": segment.data.hex(),
                "crc16": segment.crc16,
            }
            for segment in package.segments
        ],
    }


def _wait_progress_finish(
    build_frame: Callable[[str, dict[str, Any] | None], bytes],
    receive_di: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        decoded = receive_di(
            "QUERY_PROGRESS",
            build_frame("E8000704", None),
            min(5.0, max(0.1, deadline - time.monotonic())),
            "E8000704",
            retry_count=0,
        )
        payload = payload_from_decoded(decoded)
        progress = int(payload.get("progress", 255))
        failed = int(payload.get("failed_node_count", 0))
        if progress == 0:
            return {"mode": "progress", "progress": progress, "failed_node_count": failed}
        if progress == 2:
            raise RuntimeError(f"file processing incomplete, failed_node_count={failed}")
        time.sleep(1.0)
    raise RuntimeError("finish progress timeout")


def _write_progress_bar(transferred: int, total: int, remaining: int, percent: float) -> None:
    if not sys.stdout.isatty():
        return
    filled = int(percent // 5)
    bar = "#" * filled + "-" * (20 - filled)
    print(
        f"\rUPG: progress [{bar}] {transferred}/{total} ({percent:.1f}%) remaining={remaining}",
        end="",
        flush=True,
    )


def _finish_progress_bar() -> None:
    if sys.stdout.isatty():
        print()
