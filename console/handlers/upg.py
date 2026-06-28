"""/upg 命令处理器 — CSG AFN=07 文件传输/固件升级（带帧缓存）。

流程: 读取固件 → 构建帧缓存(.upg_cache) → 发送文件信息 → 逐段传输(查缓存) → ACK/NAK → 完成。

缓存文件与固件同名，后缀 .upg_cache，存储所有预构造的帧 hex。
已存在且固件未变时跳过构建阶段。

参数:
  --file        固件文件路径 (必须)
  --segment-size 分段大小 (128/256/512/1024, 默认 1024)
  --timeout     每段超时秒数 (默认 5)
  --retries     每段重试次数 (默认 3)
  --dest        目标地址 (默认 000000000000)
  --name        串口连接名 (默认 default)
  --no-cache    跳过缓存，强制重新构造
  --build-only  仅构造缓存，不执行传输
"""

from __future__ import annotations

import hashlib, json, time
from pathlib import Path
from typing import Any

from console.api import exec_cmd
from console.response import ok, fail, missing_param
from protocol_tool.utils.logger import log_serial

ROOT = Path(__file__).resolve().parent.parent.parent


def handle(args: dict[str, Any]) -> dict:
    file_path = args.get("file", "")
    if not file_path:
        return missing_param("file", "str", examples=["/path/to/firmware.bin", "database/bin/app.bin"])

    fp = Path(file_path)
    if not fp.exists():
        return fail(f"file not found: {file_path}")

    try:
        file_data = fp.read_bytes()
    except Exception as e:
        return fail(f"failed to read file: {e}")

    file_size = len(file_data)
    file_hash = hashlib.md5(file_data).hexdigest()[:8]
    segment_size = int(args.get("segment-size", "1024"))
    if segment_size not in (128, 256, 512, 1024):
        return fail(f"segment-size must be 128/256/512/1024, got {segment_size}")

    timeout = float(args.get("timeout", "5"))
    retries = int(args.get("retries", "3"))
    use_cache = not args.get("no-cache")
    build_only = args.get("build-only")

    cache_path = fp.with_suffix(fp.suffix + ".upg_cache")

    # Phase 0: 构建帧缓存
    if use_cache and cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache.get("file_hash") != file_hash or cache.get("segment_size") != segment_size:
            use_cache = False

    if not use_cache or not cache_path.exists():
        cache = _build_cache(fp.name, file_data, segment_size, file_hash, file_size)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    else:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    total_segments = cache["total_segments"]

    results = {
        "file": str(fp.name), "file_size": file_size,
        "total_segments": total_segments, "segment_size": segment_size,
        "file_crc": cache["file_crc"], "cached": use_cache,
    }

    if build_only:
        results["frames_built"] = len(cache["frames"])
        results["cache_path"] = str(cache_path)
        return ok(results)

    # 检查串口
    from wireforge_serial.api import get_connection
    conn_name = str(args.get("name") or args.get("id") or "default")
    results["name"] = conn_name
    transport = get_connection(conn_name)
    if not transport:
        return fail(f"serial not connected (name={conn_name}). use /serial connect --name {conn_name} first")

    log_serial("upg_start", port="", data={
        "name": conn_name,
        "file": str(fp.name), "size": file_size,
        "segments": total_segments, "segment_size": segment_size,
        "cached": use_cache,
    })

    # Phase 1: 发送文件信息帧 (从缓存取)
    info_hex = cache["frames"].get("file_info")
    if not info_hex:
        return fail("cache missing file_info frame")

    info_frame = bytes.fromhex(info_hex)
    resp = _send_and_wait(transport, info_frame, timeout, retries)
    if not resp:
        return fail("no response to file info", detail=results)

    if not _parse_ack(resp):
        return fail("device NAK or no ACK for file info", detail=results)
    results["file_info_ack"] = True

    # Phase 2: 逐段传输 (从缓存查帧)
    sent = 0
    failed_segments = []
    start_time = time.monotonic()

    for i in range(1, total_segments + 1):
        seg_hex = cache["frames"].get(str(i))
        if not seg_hex:
            failed_segments.append(i)
            continue

        seg_frame = bytes.fromhex(seg_hex)
        seg_timeout = timeout * 3 if i == total_segments else timeout
        resp = _send_and_wait(transport, seg_frame, seg_timeout, retries)

        if resp and _parse_ack(resp):
            sent += 1
        else:
            failed_segments.append(i)
            if len(failed_segments) > retries:
                results["sent_segments"] = sent
                results["failed_segments"] = failed_segments
                return fail(f"too many segment failures ({len(failed_segments)})", detail=results)

    elapsed = time.monotonic() - start_time
    results["sent_segments"] = sent
    results["failed_segments"] = failed_segments
    results["duration_seconds"] = round(elapsed, 1)
    results["success"] = len(failed_segments) == 0

    log_serial("upg_complete", port="", data=results)

    if results["success"]:
        return ok(results)
    return fail(f"{len(failed_segments)} segments failed", detail=results)


# ── 缓存构建 ─────────────────────────────────────────────────────────

def _build_cache(name: str, data: bytes, seg_size: int, file_hash: str, file_size: int) -> dict:
    """构建所有帧的缓存。返回 {frames: {file_info: hex, "1": hex, ...}, ...}"""
    segments = _segment_file(data, seg_size)
    total = len(segments)
    file_crc = _crc16_modbus(data)
    file_crc_str = f"0x{file_crc:04X}"

    cache: dict[str, str] = {}
    built = 0
    total_frames = total + 1  # file_info + N segments
    last_progress = -1

    # 文件信息帧
    r = exec_cmd("build", {
        "proto": "csg", "afn": "0x07", "di": "E8020701",
        "dir": "downlink",
        "file_type": "0x02",
        "file_id": "0x00",
        "dest_addr": "999999999999",
        "total_segments": total,
        "file_size": file_size,
        "file_crc": file_crc,
        "timeout_minutes": 30,
    })
    if r.get("status") == "success" and r.get("data", {}).get("frame"):
        cache["file_info"] = r["data"]["frame"]
        built += 1

    # 分段帧
    for i, seg in enumerate(segments):
        segment_crc = _crc16_modbus(seg)
        r = exec_cmd("build", {
            "proto": "csg", "afn": "0x07", "di": "E8020702",
            "dir": "downlink",
            "segment_index": i,
            "segment_length": len(seg),
            "segment_data": seg,
            "segment_crc": segment_crc,
        })
        if r.get("status") == "success" and r.get("data", {}).get("frame"):
            cache[str(i + 1)] = r["data"]["frame"]
            built += 1

        # 进度条
        progress = (built * 100) // total_frames
        if progress != last_progress:
            bar = "#" * (progress // 5) + "-" * (20 - progress // 5)
            print(f"\r  building cache: [{bar}] {built}/{total_frames} ({progress}%)", end="", flush=True)
            last_progress = progress

    print()  # newline after progress bar

    return {
        "file_name": name, "file_hash": file_hash, "file_size": file_size,
        "segment_size": seg_size, "total_segments": total,
        "file_crc": file_crc_str, "frames": cache,
    }


# ── helpers ───────────────────────────────────────────────────────────

def _segment_file(data: bytes, seg_size: int) -> list[bytes]:
    return [data[i:i+seg_size] for i in range(0, len(data), seg_size)]


def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _send_and_wait(transport, frame: bytes, timeout: float, retries: int) -> bytes | None:
    for attempt in range(retries):
        try:
            transport.write(frame)
            resp = transport.read_response(timeout)
            if resp:
                return resp
        except Exception:
            pass
        time.sleep(0.1)
    return None


def _parse_ack(data: bytes) -> bool:
    try:
        r = exec_cmd("decode", {"proto": "csg", "hex": data.hex(" ")})
        if r.get("status") == "success":
            result = r.get("data", {}).get("values", {}).get("result")
            return result == 0
    except Exception:
        pass
    return False
