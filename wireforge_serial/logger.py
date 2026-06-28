"""串口专用日志 — 记录 TX/RX、连接/断连、参数变更。

日志位置: log/serial.log
格式: [timestamp] [DEVICE_NAME] EVENT: data

只在文件中记录串口相关内容，不混合协议解析等日志。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TextIO

_LOG_DIR = Path(__file__).resolve().parent.parent / "log"
_FILE: str | None = None


def _ensure() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def _ts() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + now.strftime("%z")


def _write(line: str) -> None:
    _ensure()
    log_path = _LOG_DIR / "serial.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def log_connect(device: str, port: str, baudrate: int,
                bytesize: int = 8, parity: str = "N", stopbits: float = 1.0) -> None:
    """记录串口连接事件。"""
    _write(f"[{_ts()}] [{device}] CONNECT {port} @ {baudrate} {bytesize}{parity}{_fmt_stopbits(stopbits)}")


def log_disconnect(device: str, reason: str = "") -> None:
    """记录串口断连事件。"""
    msg = f"[{_ts()}] [{device}] DISCONNECT"
    if reason:
        msg += f" (reason: {reason})"
    _write(msg)


def log_tx(device: str, data: bytes) -> None:
    """记录串口发送数据。"""
    _write(f"[{_ts()}] [{device}] TX: {data.hex(' ').upper()}")


def log_rx(device: str, data: bytes) -> None:
    """记录串口接收数据。"""
    _write(f"[{_ts()}] [{device}] RX: {data.hex(' ').upper()}")


def log_rx_timeout(device: str, timeout: float) -> None:
    """记录接收超时。"""
    _write(f"[{_ts()}] [{device}] RX: <timeout {timeout}s>")


def log_rx_error(device: str, error: str) -> None:
    """记录接收异常。"""
    _write(f"[{_ts()}] [{device}] RX: <error: {error}>")


def log_config_change(device: str, changes: dict, current: dict) -> None:
    """记录串口参数变更。"""
    _write(f"[{_ts()}] [{device}] CONFIG changed={changes} current={current}")


def log_event(device: str, event: str, detail: str = "") -> None:
    """记录通用串口事件。"""
    msg = f"[{_ts()}] [{device}] {event}"
    if detail:
        msg += f" {detail}"
    _write(msg)


def _fmt_stopbits(val: float) -> str:
    if val == 1.0:
        return "1"
    if val == 1.5:
        return "1.5"
    if val == 2.0:
        return "2"
    return str(val)


# ── 实时终端显示 ────────────────────────────────────────────────────────

def display_tx(device: str, data: bytes, out: TextIO | None = None) -> None:
    """实时打印发送数据到终端。"""
    import sys
    (out or sys.stdout).write(f"[{device}] TX: {data.hex(' ').upper()}\n")
    (out or sys.stdout).flush()


def display_rx(device: str, data: bytes, out: TextIO | None = None) -> None:
    """实时打印接收数据到终端。"""
    import sys
    (out or sys.stdout).write(f"[{device}] RX: {data.hex(' ').upper()}\n")
    (out or sys.stdout).flush()


def display_rx_timeout(device: str, timeout: float, out: TextIO | None = None) -> None:
    """实时打印接收超时。"""
    import sys
    (out or sys.stdout).write(f"[{device}] RX: <timeout {timeout}s>\n")
    (out or sys.stdout).flush()


def display_connect(device: str, port: str, baudrate: int,
                    bytesize: int = 8, parity: str = "N", stopbits: float = 1.0,
                    out: TextIO | None = None) -> None:
    """实时打印连接事件到终端。"""
    import sys
    (out or sys.stdout).write(
        f"[{device}] Connected to {port} @ {baudrate} {bytesize}{parity}{_fmt_stopbits(stopbits)}\n"
    )
    (out or sys.stdout).flush()


def display_disconnect(device: str, reason: str = "", out: TextIO | None = None) -> None:
    """实时打印断连事件到终端。"""
    import sys
    msg = f"[{device}] Disconnected"
    if reason:
        msg += f" ({reason})"
    (out or sys.stdout).write(msg + "\n")
    (out or sys.stdout).flush()
