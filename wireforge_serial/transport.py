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
import time
import uuid
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
        with open(self._file, "a") as f:
            f.write(record + "\n")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._file.exists():
            return b""
        with open(self._file) as f:
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

    def open(self):
        port = self.settings.port
        if port == "mock://loop":
            self._port = _MockLoopPort()
        elif port.startswith("mock://"):
            raise RuntimeError("unknown mock port. Supported mock port: mock://loop")
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
        if self._port:
            self._port.close()
            self._port = None

    def write(self, data: bytes) -> int:
        if not self._port:
            raise RuntimeError("port not open")
        try:
            return self._port.write(data)
        except Exception as e:
            self._last_error = str(e)
            raise

    def read_available(self, max_size: int = 4096) -> bytes:
        if not self._port:
            return b""
        try:
            return self._port.read(max_size)
        except Exception as e:
            self._last_error = str(e)
            return b""

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
        """轮询读取直到超时，空闲后返回完整响应。"""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        idle_deadline = None

        while time.monotonic() < deadline:
            chunk = self.read_available(4096)
            if chunk:
                buf.extend(chunk)
                idle_deadline = time.monotonic() + idle_timeout
            if idle_deadline and time.monotonic() >= idle_deadline:
                break
            time.sleep(0.01)

        return bytes(buf)

    @staticmethod
    def available_ports() -> list[str]:
        ports = ["mock://loop", "virtual://demo"]
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
