"""串口 JSON API — 连接、发送、断开。

send 只写 TX，不读 RX；接收由后台 monitor 与 /wait-frame 处理。
输入/输出均为 JSON 格式，所有操作自动记录到 log/serial.log。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any

from wireforge_serial.transport import SerialTransport, SerialSettings
from wireforge_serial.logger import (
    log_connect, log_disconnect, log_tx, log_rx, log_rx_error,
    display_tx, display_rx, display_connect, display_disconnect,
)

# 全局连接实例 — 所有串口后台运行，无 active 概念
_connections: dict[str, SerialTransport] = {}
_connection_meta: dict[str, dict[str, Any]] = {}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class SerialResult:
    success: bool
    operation: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"success": self.success, "operation": self.operation}
        if self.data: d["data"] = self.data
        if self.error: d["error"] = self.error
        return d


# ── API ───────────────────────────────────────────────────────────────

def serial_open(args: dict[str, Any]) -> SerialResult:
    """打开串口。

    args: {port, baudrate?, bytesize?, parity?, stopbits?, timeout?, id?}
    """
    args = _normalize_args(args)
    port = args.get("port", "")
    if not port:
        return SerialResult(False, "open", error="port is required")

    cid = _connection_id(args)
    invalid = _validate_name(cid)
    if invalid:
        return SerialResult(False, "open", error=invalid)

    occupied_by = _port_occupied_by(port, cid)
    if occupied_by:
        return SerialResult(
            False,
            "open",
            error=f"PORT_ALREADY_IN_USE: {port} is already bound to {occupied_by}",
        )

    settings = SerialSettings(
        port=port,
        baudrate=args.get("baudrate", 9600),
        bytesize=args.get("bytesize", 8),
        parity=args.get("parity", "N"),
        stopbits=args.get("stopbits", 1.0),
        timeout=args.get("timeout", 0.05),
    )

    try:
        if cid in _connections:
            _connections[cid].close()
            _connections.pop(cid, None)
            _connection_meta.pop(cid, None)
        t = SerialTransport(settings)
        t.open()
        bind_rx_display(t, cid)
        t.start_rx_monitor()
        _connections[cid] = t
        _connection_meta[cid] = {
            "id": cid,
            "to": cid,
            "port": port,
            "baudrate": settings.baudrate,
            "bytesize": settings.bytesize,
            "parity": settings.parity,
            "stopbits": settings.stopbits,
            "timeout": settings.timeout,
            "display": args.get("display", "hex"),
            "state": "connected",
            "created_at": _now(),
            "last_error": "",
        }
        result = SerialResult(True, "open", data={
            "id": cid, "to": cid, "port": port, "baudrate": settings.baudrate,
            "bytesize": settings.bytesize, "parity": settings.parity,
            "stopbits": settings.stopbits, "status": "connected",
        })
        log_connect(cid, port, settings.baudrate, settings.bytesize,
                    settings.parity, settings.stopbits)
        display_connect(cid, port, settings.baudrate, settings.bytesize,
                        settings.parity, settings.stopbits)
        return result
    except Exception as e:
        return SerialResult(False, "open", error=str(e))


def serial_send(args: dict[str, Any]) -> SerialResult:
    """发送数据（不读 RX；接收由后台 monitor 与 /wait-frame 处理）。

    args: {hex, id?}
    """
    args = _normalize_args(args)
    cid = _connection_id(args)
    t = _connections.get(cid)
    if not t:
        return SerialResult(False, "send", error=f"not connected (to={cid})")

    hex_str = str(args.get("hex", "")).replace(" ", "").replace("\n", "")
    if not hex_str:
        return SerialResult(False, "send", error="hex is required")

    try:
        data = bytes.fromhex(hex_str)
    except ValueError as e:
        return SerialResult(False, "send", error=str(e))

    try:
        if not t.connected:
            reason = getattr(t, '_last_error', '') or "port not open"
            _connections.pop(cid, None)
            _mark_disconnected(cid, reason)
            log_disconnect(cid, reason)
            display_disconnect(cid, reason)
            return SerialResult(False, "send", error=reason)

        bind_rx_display(t, cid)
        written = write_with_tx_display(t, cid, data)

        disconnect_reason = ""
        if not t.connected:
            disconnect_reason = getattr(t, '_last_error', '') or "port not open"
            _connections.pop(cid, None)
            _mark_disconnected(cid, disconnect_reason)
            log_disconnect(cid, disconnect_reason)
            display_disconnect(cid, disconnect_reason)

        result = SerialResult(True, "send", data={
            "id": cid, "to": cid, "sent": data.hex(" ").upper(),
            "sent_bytes": written,
        })
        if disconnect_reason:
            result.data["warning"] = f"disconnected: {disconnect_reason}"
        return result
    except Exception as e:
        t.on_tx = None
        log_rx_error(cid, str(e))
        _set_last_error(cid, str(e))
        return SerialResult(False, "send", error=str(e))


def serial_close(args: dict[str, Any]) -> SerialResult:
    """关闭串口。

    args: {id?}
    """
    args = _normalize_args(args)
    cid = _connection_id(args)
    t = _connections.pop(cid, None)
    if not t:
        return SerialResult(False, "close", error=f"not connected (to={cid})")
    try:
        t.close()
        _mark_disconnected(cid, "")
        result = SerialResult(True, "close", data={"id": cid, "to": cid, "status": "closed"})
        log_disconnect(cid)
        display_disconnect(cid)
        return result
    except Exception as e:
        return SerialResult(False, "close", error=str(e))


def serial_ports(args: dict[str, Any] | None = None) -> SerialResult:
    """列出可用串口。"""
    try:
        ports = SerialTransport.available_ports()
        connected = list(_connections.keys())
        connections = [_connection_snapshot(cid) for cid in sorted(_connection_meta)]
        return SerialResult(True, "ports", data={
            "available": ports, "connected": connected,
            "connections": connections,
        })
    except Exception as e:
        return SerialResult(False, "ports", error=str(e))


def list_connected_names() -> list[str]:
    """Return sorted names of currently open serial connections."""
    return sorted(_connections.keys())


def _auto_detect_name() -> str | None:
    """如果只有一个已连接串口，返回其名称；否则返回 None（需用户显式指定）。"""
    connected = list(_connections.keys())
    if len(connected) == 1:
        return connected[0]
    return None


def get_connection(name: str | None = None) -> SerialTransport | None:
    """获取连接。name 为空时自动检测唯一连接。"""
    cid = name or _auto_detect_name()
    if cid is None:
        return None
    return _connections.get(cid)


def get_connection_settings(name: str) -> dict[str, Any] | None:
    meta = _connection_meta.get(name)
    if not meta:
        return None
    return {
        "port": meta.get("port", "mock://loop"),
        "baudrate": meta.get("baudrate", 9600),
        "bytesize": meta.get("bytesize", 8),
        "parity": meta.get("parity", "N"),
        "stopbits": meta.get("stopbits", 1.0),
        "timeout": meta.get("timeout", 0.05),
    }


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Canonical serial connection target is ``to`` (aliases: conn, id; ``name`` for management CLI)."""
    normalized = dict(args)
    if not normalized.get("to"):
        for alias in ("conn", "name", "id"):
            val = normalized.get(alias)
            if val not in (None, ""):
                normalized["to"] = val
                break
    if normalized.get("to") not in (None, ""):
        normalized["id"] = str(normalized["to"])
    return normalized


def _connection_id(args: dict[str, Any]) -> str:
    """获取连接 ID。优先显式 ``to``/``id``；单连接时自动检测。"""
    explicit = args.get("to") or args.get("id")
    if explicit:
        return str(explicit)
    auto = _auto_detect_name()
    if auto:
        return auto
    return str(args.get("to") or args.get("id") or "")


def _validate_name(name: str) -> str:
    if _NAME_RE.match(name):
        return ""
    return (
        f"invalid connection target: {name}. "
        "Use [A-Za-z_][A-Za-z0-9_-]*"
    )


def _is_physical_port(port: str) -> bool:
    return not (port == "mock://loop" or port.startswith("virtual://"))


def _port_occupied_by(port: str, cid: str) -> str:
    if not _is_physical_port(port):
        return ""
    for name, meta in _connection_meta.items():
        if name != cid and meta.get("state") == "connected" and meta.get("port") == port:
            return name
    return ""


def _connection_snapshot(cid: str) -> dict[str, Any]:
    meta = dict(_connection_meta.get(cid, {}))
    transport = _connections.get(cid)
    if transport and not transport.connected:
        _connections.pop(cid, None)
        _mark_disconnected(cid, getattr(transport, "_last_error", "") or "port not open")
        meta = dict(_connection_meta.get(cid, meta))
    if not meta:
        meta = {"id": cid, "to": cid}
    meta["state"] = "connected" if cid in _connections else meta.get("state", "disconnected")
    meta.setdefault("display", "hex")
    return meta


def _mark_disconnected(cid: str, reason: str) -> None:
    meta = _connection_meta.get(cid)
    if not meta:
        return
    meta["state"] = "disconnected"
    meta["last_error"] = reason


def _set_last_error(cid: str, reason: str) -> None:
    meta = _connection_meta.get(cid)
    if meta:
        meta["last_error"] = reason


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def bind_rx_display(transport: SerialTransport, cid: str) -> None:
    """绑定 RX 实时打印与日志（connect 后默认启用；可重复调用恢复）。"""
    transport.on_rx_chunk = lambda d: _log_and_display_rx(cid, d)


def bind_rx_quiet(transport: SerialTransport, cid: str) -> None:
    """升级等场景：仅写 serial.log，不在终端打印 RX，也不触发 auto_rule。"""
    transport.on_rx_chunk = lambda d: _log_rx_quiet(cid, d)


def write_with_tx_display(transport: SerialTransport, cid: str, data: bytes) -> int:
    """发送并实时打印/记录 TX；发送后清除 on_tx。"""
    transport.on_tx = lambda d: _log_and_display_tx(cid, d)
    try:
        return transport.write(data)
    finally:
        transport.on_tx = None


def write_quiet(transport: SerialTransport, cid: str, data: bytes) -> int:
    """发送并仅写 serial.log，不在终端打印 TX。"""
    log_tx(cid, data)
    return transport.write(data)


def _log_rx_quiet(device: str, data: bytes) -> None:
    log_rx(device, data)
    try:
        from console.runtime import update_last_rx

        update_last_rx({
            "id": device,
            "to": device,
            "rx": data.hex(" ").upper(),
            "rx_bytes": len(data),
        })
    except Exception:
        pass


def _log_and_display_tx(device: str, data: bytes) -> None:
    """实时打印 + 日志记录发送数据。"""
    log_tx(device, data)
    display_tx(device, data)


def _log_and_display_rx(device: str, data: bytes) -> None:
    """实时打印 + 日志记录接收数据。"""
    log_rx(device, data)
    display_rx(device, data)
    try:
        from console.runtime import update_last_rx

        update_last_rx({
            "id": device,
            "to": device,
            "rx": data.hex(" ").upper(),
            "rx_bytes": len(data),
        })
    except Exception:
        pass
    try:
        from console.handlers.auto_rule import process_rx_chunk

        process_rx_chunk(device, data)
    except Exception:
        pass
