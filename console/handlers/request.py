"""/request 命令处理器 — 发送报文并等待匹配响应（自动化测试原语）。

用法:
  /request --name cco --send "68 0C 00 40 03 01 01 03 00 E8 30 16" \\
    --wait.afn 00 --wait.di E8010001 --timeout 3000

  # 也支持发送结构化数据:
  /request --name cco --proto csg --afn 03 --di E8000301 --dir downlink \\
    --wait.afn 00 --timeout 3000

成功时返回:
  {"status": "success", "elapsed_ms": 842,
   "request": {"frame_hex": "68 ... 16", "decoded": {...}},
   "response": {"frame_hex": "68 ... 16", "decoded": {...}}}

失败时返回:
  {"status": "fail", "error": "timeout: no response matched wait conditions",
   "detail": {"request_sent": true, "timeout_ms": 3000, ...}}
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from console.handlers.frame_splitter import split_frames
from console.handlers.wait_frame import (
    _parse_expect, _try_decode, _flatten_decode_values, _match_expect,
)
from console.response import ok, fail
from protocol_tool.utils.logger import log_serial

ROOT = Path(__file__).resolve().parent.parent.parent


def handle(args: dict[str, Any]) -> dict:
    name = str(args.get("name") or args.get("id") or "default")
    timeout_ms = int(args.get("timeout", "5000"))
    protocol = str(args.get("proto") or args.get("protocol", ""))

    # 检查串口
    from wireforge_serial.api import get_connection
    transport = get_connection(name)
    if not transport:
        return fail(f"serial not connected (name={name}). use /serial connect --name {name} first")

    # ── 解析 --send ──
    send_hex = _resolve_send(args)
    if not send_hex:
        return fail("no --send hex provided")

    try:
        send_frame = bytes.fromhex(send_hex.replace(" ", ""))
    except ValueError as e:
        return fail(f"invalid --send hex: {e}")

    # ── 解析 --wait 条件 ──
    wait_args = _extract_wait_args(args)
    wait_conditions = _parse_expect(wait_args)
    if not wait_conditions:
        return fail("no --wait conditions. Use --wait.afn, --wait.di, --wait.dir etc.")

    # ── 发送 ──
    from wireforge_serial.logger import log_tx, log_rx, display_tx, display_rx

    transport.on_tx = lambda d: (_log_and_display(name, d, "TX"))
    transport.on_rx_chunk = lambda d: (_log_and_display(name, d, "RX"))

    try:
        transport.write(send_frame)
    except Exception as e:
        transport.on_tx = None
        transport.on_rx_chunk = None
        return fail(f"send failed: {e}")

    # ── 解码请求帧 ──
    request_decoded = _try_decode(send_frame, protocol)

    # ── 等待响应 ──
    log_serial("request_start", port=name, data={
        "timeout_ms": timeout_ms, "send_hex": send_hex,
        "wait_conditions": wait_conditions,
    })

    deadline = time.monotonic() + timeout_ms / 1000.0
    buffer = bytearray()
    received_count = 0
    decoded_count = 0
    last_decoded: dict[str, Any] = {}
    mismatch_summary: list[str] = []
    t0 = time.monotonic()

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        chunk = transport.read_response(min(0.2, remaining))
        if chunk:
            buffer.extend(chunk)

        data = bytes(buffer)
        frames, remainder = split_frames(data)
        buffer = bytearray(remainder)

        for frame_bytes in frames:
            received_count += 1
            frame_hex = frame_bytes.hex(" ").upper()

            decoded = _try_decode(frame_bytes, protocol)
            if decoded is None:
                mismatch_summary.append(f"frame[{received_count}]: decode failed")
                continue

            decoded_count += 1
            last_decoded = decoded

            match_result = _match_expect(decoded, wait_conditions, received_count)
            if match_result is True:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                result_data = {
                    "elapsed_ms": elapsed_ms,
                    "request": {
                        "frame_hex": send_frame.hex(" ").upper(),
                        "decoded": request_decoded,
                    },
                    "response": {
                        "frame_hex": frame_hex,
                        "decoded": decoded,
                        "frame_index": received_count,
                    },
                }
                log_serial("request_match", port=name, data=result_data)
                transport.on_tx = None
                transport.on_rx_chunk = None
                return ok(result_data)

            mismatch_summary.append(match_result)

        time.sleep(0.02)

    # Timeout
    transport.on_tx = None
    transport.on_rx_chunk = None

    log_serial("request_timeout", port=name, data={
        "timeout_ms": timeout_ms, "received_frames": received_count,
    })
    return fail("timeout: no response matched wait conditions", detail={
        "request_sent": True,
        "request_frame": send_frame.hex(" ").upper(),
        "timeout_ms": timeout_ms,
        "received_frames": received_count,
        "decoded_frames": decoded_count,
        "last_decoded": last_decoded,
        "mismatch_summary": mismatch_summary,
    })


# ── helpers ─────────────────────────────────────────────────────────────

def _resolve_send(args: dict[str, Any]) -> str:
    """解析 --send 参数。

    支持:
      --send "68 0C 00 40 ..."
      --send.frame=...
    """
    send = args.get("send")
    if send:
        return str(send)
    send_frame = args.get("send.frame")
    if send_frame:
        return str(send_frame)
    # 支持位置参数
    pos = args.get("_", [])
    if pos:
        return str(pos[0])
    return ""


def _extract_wait_args(args: dict[str, Any]) -> dict[str, Any]:
    """从 --wait.xxx 参数提取等待条件，映射为 expect.xxx 格式。"""
    wait_args: dict[str, Any] = {}
    for key, val in args.items():
        if key.startswith("wait.") and val is not None:
            # --wait.afn=04 → expect.afn=04
            expect_key = "expect." + key[len("wait."):]
            wait_args[expect_key] = val
        elif key == "wait" and val is not None:
            # --wait='{"all":[...]}' → expect
            wait_args["expect"] = val
    # 也接受直接的 expect.xxx 参数
    for key, val in args.items():
        if key.startswith("expect.") and val is not None:
            wait_args.setdefault(key, val)
        elif key == "expect" and val is not None:
            wait_args.setdefault("expect", val)
    return wait_args


def _log_and_display(device: str, data: bytes, direction: str) -> None:
    """实时打印 + 日志记录。"""
    from wireforge_serial.logger import log_tx, log_rx, display_tx, display_rx
    if direction == "TX":
        log_tx(device, data)
        display_tx(device, data)
    else:
        log_rx(device, data)
        display_rx(device, data)
