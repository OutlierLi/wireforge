"""串口传输层 — 封装 pyserial / mock / virtual 三种后端。

用法:
    settings = SerialSettings(port="/dev/ttyUSB0", baudrate=9600)
    with SerialTransport(settings) as t:
        t.write(frame_bytes)
        response = t.read_response(timeout=1.0)

Mock 模式: port="mock://loop" — 内存回环
Virtual 模式: port="virtual://demo" — 跨进程 JSONL 文件总线
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


# ── Serial Settings ───────────────────────────────────────────────────

@dataclass
class SerialSettings:
    port: str = "mock://loop"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    timeout: float = 0.05

    def __post_init__(self):
        self.parity = self._normalize_parity(self.parity)
        if self.stopbits not in (1, 1.5, 2):
            self.stopbits = 1.0

    @staticmethod
    def _normalize_parity(p: str) -> str:
        p = p.strip().upper()
        m = {"无校验": "N", "奇校验": "O", "偶校验": "E", "NONE": "N", "ODD": "O", "EVEN": "E"}
        return m.get(p, p if p in "NOE" else "N")

    def to_dict(self) -> dict:
        return {
            "port": self.port, "baudrate": self.baudrate,
            "bytesize": self.bytesize, "parity": self.parity,
            "stopbits": self.stopbits,
        }


# ── Port Protocol ─────────────────────────────────────────────────────

class _PortLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def close(self) -> None: ...


# ── Mock Loopback ─────────────────────────────────────────────────────

class _MockLoopPort:
    """内存回环：写入的字节立即可读。"""
    def __init__(self):
        self._buf = bytearray()

    def write(self, data: bytes) -> int:
        self._buf.extend(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        n = min(size, len(self._buf))
        result = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return result

    def close(self):
        self._buf.clear()


# ── Auto Rule Loopback ─────────────────────────────────────────────────

class _AutoRulePort:
    """自动规则回环：写入 → auto_rule 匹配 → 匹配到的 reply 变成 RX。

    与 mock://loop 的区别：不是直接回显，而是经过 auto_rule 引擎处理。
    规则匹配成功且有 reply/build 动作时，reply 帧作为 RX；未命中则 RX 为空。

    规则格式（与 auto_rule 模块一致）:
      condition: regex | decoded | any | all | any 组合
      actions: [{command: "/send", args: {hex: "68..."}}, ...]
               [{command: build, args: {...}}]
    """

    def __init__(self):
        self._rx_buf = bytearray()

    def prepend_rx(self, data: bytes) -> None:
        if data:
            self._rx_buf = bytearray(data) + self._rx_buf

    def write(self, data: bytes) -> int:
        try:
            from console.handlers.auto_rule import match_all, append_action_replies_to_buf

            frame_hex = data.hex().upper()
            for match_result in match_all(frame_hex, data):
                append_action_replies_to_buf(self._rx_buf, match_result.actions, data)
        except Exception:
            pass
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._rx_buf:
            return b""
        n = min(size, len(self._rx_buf))
        result = bytes(self._rx_buf[:n])
        self._rx_buf = self._rx_buf[n:]
        return result

    def close(self):
        self._rx_buf.clear()


# ── Virtual Bus (跨进程) ──────────────────────────────────────────────

class _VirtualBusPort:
    """跨进程 JSONL 文件总线。"""
    _bus_dir = Path("/tmp/wireforge_virtual")

    def __init__(self, name: str):
        self._bus_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._bus_dir / f"{name}.jsonl"
        self._client_id = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._offset = self._file.stat().st_size if self._file.exists() else 0

    def write(self, data: bytes) -> int:
        record = json.dumps({"client": self._client_id, "data": data.hex()})
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(record + "\n")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._file.exists():
            return b""
        with open(self._file, encoding="utf-8") as f:
            f.seek(self._offset)
            buf = bytearray()
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("client") != self._client_id:
                        buf.extend(bytes.fromhex(rec["data"]))
                except (json.JSONDecodeError, ValueError):
                    pass
            self._offset = f.tell()
        return bytes(buf[:size])

    def close(self):
        pass


# ── Serial Transport ──────────────────────────────────────────────────

class SerialTransport:
    """串口传输上下文管理器。"""

    def __init__(self, settings: SerialSettings):
        self.settings = settings
        self._port: _PortLike | None = None
        self._last_error: str = ""
        self._rx_buf = bytearray()
        self._rx_pushback = bytearray()
        self._rx_cond = threading.Condition()
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        # 实时回调: 每个读取到的 chunk 都会触发
        self.on_rx_chunk: Callable[[bytes], None] | None = None
        self.on_tx: Callable[[bytes], None] | None = None

    def open(self):
        port = self.settings.port
        if port == "mock://loop":
            self._port = _MockLoopPort()
        elif port == "mock://auto":
            self._port = _AutoRulePort()
        elif port.startswith("mock://"):
            raise RuntimeError("unknown mock port. Supported: mock://loop, mock://auto")
        elif port.startswith("virtual://"):
            name = port.replace("virtual://", "").strip("/")
            self._port = _VirtualBusPort(name or "default")
        else:
            try:
                import serial
                self._port = serial.Serial(
                    port=port, baudrate=self.settings.baudrate,
                    bytesize=self.settings.bytesize,
                    parity=self.settings.parity,
                    stopbits=self.settings.stopbits,
                    timeout=self.settings.timeout,
                )
            except (ImportError, AttributeError):
                raise RuntimeError("pyserial not installed. pip install pyserial")
            except ValueError as e:
                raise RuntimeError(f"invalid serial params: {e}") from e
            except Exception as e:
                raise RuntimeError(str(e)) from e

    def close(self):
        self.stop_rx_monitor()
        if self._port:
            self._port.close()
            self._port = None

    def write(self, data: bytes) -> int:
        if not self._port:
            raise RuntimeError("port not open")
        try:
            result = self._port.write(data)
            if self.on_tx:
                self.on_tx(data)
            return result
        except Exception as e:
            self._last_error = str(e)
            raise

    def prepend_rx(self, data: bytes) -> None:
        """Put bytes back for the next read (e.g. wait-frame consumed one of many)."""
        if not data:
            return
        if self._port is not None and hasattr(self._port, "prepend_rx"):
            self._port.prepend_rx(data)
        else:
            self._rx_pushback = bytearray(data) + self._rx_pushback

    def read_available(self, max_size: int = 4096) -> bytes:
        if not self._port:
            return b""
        try:
            if self._rx_pushback:
                n = min(max_size, len(self._rx_pushback))
                result = bytes(self._rx_pushback[:n])
                self._rx_pushback = self._rx_pushback[n:]
                return result
            return self._port.read(max_size)
        except Exception as e:
            self._last_error = str(e)
            return b""

    def start_rx_monitor(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(
            target=self._rx_monitor_loop,
            name=f"wireforge-rx-{self.settings.port}",
            daemon=True,
        )
        self._reader_thread.start()

    def stop_rx_monitor(self) -> None:
        self._reader_stop.set()
        thread = self._reader_thread
        if thread and thread.is_alive():
            thread.join(timeout=0.2)
        self._reader_thread = None

    @property
    def rx_monitoring(self) -> bool:
        return bool(self._reader_thread and self._reader_thread.is_alive())

    def clear_rx_buffer(self) -> None:
        with self._rx_cond:
            self._rx_buf.clear()

    def _rx_monitor_loop(self) -> None:
        while not self._reader_stop.is_set():
            chunk = self.read_available(4096)
            if chunk:
                with self._rx_cond:
                    self._rx_buf.extend(chunk)
                    self._rx_cond.notify_all()
                if self.on_rx_chunk:
                    self.on_rx_chunk(chunk)
            else:
                time.sleep(0.01)

    def _read_monitored_response(self, timeout: float, idle_timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        idle_deadline: float | None = None

        while time.monotonic() < deadline:
            with self._rx_cond:
                if not self._rx_buf:
                    wait_until = idle_deadline or deadline
                    self._rx_cond.wait(timeout=max(0.0, min(0.05, wait_until - time.monotonic())))
                if self._rx_buf:
                    buf.extend(self._rx_buf)
                    self._rx_buf.clear()
                    idle_deadline = time.monotonic() + idle_timeout
            if idle_deadline and time.monotonic() >= idle_deadline:
                break

        return bytes(buf)

    @property
    def connected(self) -> bool:
        """检查串口是否仍然连接。"""
        if not self._port:
            return False
        try:
            # pyserial: is_open is a property
            if hasattr(self._port, 'is_open'):
                return self._port.is_open
            return True  # mock/virtual always connected
        except Exception:
            return False

    def read_response(self, timeout: float, idle_timeout: float = 0.05) -> bytes:
        """轮询读取直到超时，空闲后返回完整响应。

        每收到一个 chunk 触发 on_rx_chunk 回调，用于实时终端显示。
        """
        if self.rx_monitoring:
            return self._read_monitored_response(timeout, idle_timeout)

        deadline = time.monotonic() + timeout
        buf = bytearray()
        idle_deadline = None

        while time.monotonic() < deadline:
            chunk = self.read_available(4096)
            if chunk:
                buf.extend(chunk)
                if self.on_rx_chunk:
                    self.on_rx_chunk(chunk)
                idle_deadline = time.monotonic() + idle_timeout
            if idle_deadline and time.monotonic() >= idle_deadline:
                break
            time.sleep(0.01)

        return bytes(buf)

    @staticmethod
    def available_ports() -> list[str]:
        ports = ["mock://loop", "mock://auto", "virtual://demo"]
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                ports.append(p.device)
        except ImportError:
            pass
        return ports

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
