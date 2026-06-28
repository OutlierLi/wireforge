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


def _parse_query_slave_info_request(data: bytes) -> tuple[int, int] | None:
    """从查询从节点信息下行帧解析 (start_slave_index, slave_count)。"""
    marker = b"\x06\x03\x03\xe8"
    pos = data.find(marker)
    if pos < 0:
        return None
    off = pos + len(marker)
    if off + 3 > len(data):
        return None
    start = int.from_bytes(data[off:off + 2], "little")
    count = data[off + 2]
    return start, count


def _build_query_slave_info_response(start: int, count: int) -> bytes | None:
    from runtime.command_runtime import execute

    addrs = [str(start + i + 1) for i in range(count)]
    result = execute("build", {
        "proto": "csg",
        "afn": "0x03",
        "di": "E8040306",
        "dir": "uplink",
        "slave_total": 1024,
        "response_slave_count": count,
        "slave_addrs": addrs,
    })
    if result.get("status") != "success":
        return None
    frame_hex = (result.get("data") or {}).get("frame", "")
    if not frame_hex:
        return None
    try:
        return bytes.fromhex(frame_hex.replace(" ", ""))
    except ValueError:
        return None


def _build_csg_ack_response() -> bytes | None:
    from runtime.command_runtime import execute

    result = execute("build", {
        "proto": "csg",
        "afn": "0x00",
        "di": "E8010001",
        "dir": "uplink",
        "wait_time": 0,
    })
    if result.get("status") != "success":
        return None
    frame_hex = (result.get("data") or {}).get("frame", "")
    if not frame_hex:
        return None
    try:
        return bytes.fromhex(frame_hex.replace(" ", ""))
    except ValueError:
        return None


def _builtin_csg_auto_reply(data: bytes) -> bytes | None:
    """mock://auto 内置 CSG 回复：查询从节点信息按请求序号生成地址，其余回确认帧。"""
    hex_str = data.hex().upper()
    if not hex_str.startswith("68") or not hex_str.endswith("16"):
        return None
    # 下行帧 control.dir=0 → 0040
    if "0040" not in hex_str:
        return None

    if "060303E8" in hex_str:
        parsed = _parse_query_slave_info_request(data)
        if parsed:
            start, count = parsed
            return _build_query_slave_info_response(start, count)
        return None

    # 查询从节点数量等其它下行请求默认回确认（也可由 auto_rule 覆盖）
    return _build_csg_ack_response()


# ── Auto Rule Loopback ─────────────────────────────────────────────────

class _AutoRulePort:
    """自动规则回环：写入 → auto_rule 匹配 → 匹配到的 reply 变成 RX。

    与 mock://loop 的区别：不是直接回显，而是经过 auto_rule 引擎处理。
    如果规则匹配成功且有 reply 动作，reply 帧作为 RX；否则尝试内置 CSG 回复；
    仍无匹配则 RX 为空。

    规则格式（与 auto_rule 模块一致）:
      condition.type: regex | decoded | any
      condition.pattern: 正则或 hex 匹配模式（匹配 frame.hex().upper()，无空格）
      actions: [{command: "/send", args: {hex: "68..."}}, ...]
    """

    def __init__(self):
        self._rx_buf = bytearray()

    def write(self, data: bytes) -> int:
        try:
            from console.handlers.auto_rule import _rules, _match_rule

            for rule in _rules.values():
                if not rule.get("enabled", True):
                    continue
                match_result = _match_rule(rule, data)
                if match_result:
                    self._append_action_replies(match_result.actions)

            if not self._rx_buf:
                builtin = _builtin_csg_auto_reply(data)
                if builtin:
                    self._rx_buf.extend(builtin)
        except Exception:
            pass
        return len(data)

    def _append_action_replies(self, actions: list[dict]) -> None:
        for action in actions:
            cmd = action.get("command", "")
            act_args = action.get("args", {})
            if cmd in ("/send", "send"):
                reply_hex = act_args.get("hex", "")
                if reply_hex:
                    try:
                        self._rx_buf.extend(bytes.fromhex(reply_hex.replace(" ", "")))
                    except ValueError:
                        pass
            elif cmd in ("/serial", "serial") and act_args.get("sub") == "send":
                reply_hex = act_args.get("hex", "")
                if reply_hex:
                    try:
                        self._rx_buf.extend(bytes.fromhex(reply_hex.replace(" ", "")))
                    except ValueError:
                        pass

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
        """轮询读取直到超时，空闲后返回完整响应。

        每收到一个 chunk 触发 on_rx_chunk 回调，用于实时终端显示。
        """
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
