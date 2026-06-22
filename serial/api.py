"""串口 JSON API — 连接、发送、接收、断开。

输入/输出均为 JSON 格式，所有操作自动记录到 log/serial.log。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from serial.transport import SerialTransport, SerialSettings
from protocol_tool.utils.logger import log_serial

# 全局连接实例
_connections: dict[str, SerialTransport] = {}


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
    port = args.get("port", "")
    if not port:
        return SerialResult(False, "open", error="port is required")

    cid = args.get("id", "default")
    if cid in _connections:
        _connections[cid].close()

    settings = SerialSettings(
        port=port,
        baudrate=args.get("baudrate", 9600),
        bytesize=args.get("bytesize", 8),
        parity=args.get("parity", "N"),
        stopbits=args.get("stopbits", 1.0),
        timeout=args.get("timeout", 0.05),
    )

    try:
        t = SerialTransport(settings)
        t.open()
        _connections[cid] = t
        result = SerialResult(True, "open", data={
            "id": cid, "port": port, "baudrate": settings.baudrate,
            "status": "connected",
        })
        log_serial("open", port=port, data=result.data)
        return result
    except Exception as e:
        log_serial("open", port=port, success=False, error=str(e))
        return SerialResult(False, "open", error=str(e))


def serial_send(args: dict[str, Any]) -> SerialResult:
    """发送数据并等待响应。

    args: {hex, timeout?, id?}
    """
    cid = args.get("id", "default")
    t = _connections.get(cid)
    if not t:
        return SerialResult(False, "send", error=f"not connected (id={cid})")

    hex_str = str(args.get("hex", "")).replace(" ", "").replace("\n", "")
    if not hex_str:
        return SerialResult(False, "send", error="hex is required")

    try:
        data = bytes.fromhex(hex_str)
    except ValueError as e:
        return SerialResult(False, "send", error=str(e))

    timeout = float(args.get("timeout", 1.0))
    try:
        # 先检查连接状态
        if not t.connected:
            reason = getattr(t, '_last_error', '') or "port not open"
            _connections.pop(cid, None)
            log_serial("disconnect", port="", success=False,
                       error=reason, data={"id": cid, "reason": reason})
            return SerialResult(False, "send", error=reason)

        written = t.write(data)
        response = t.read_response(timeout)

        # 发送后再次检查连接状态
        disconnect_reason = ""
        if not t.connected:
            disconnect_reason = getattr(t, '_last_error', '') or "port not open"
            _connections.pop(cid, None)
            log_serial("disconnect", port="", success=False,
                       error=disconnect_reason, data={"id": cid, "reason": disconnect_reason})

        result = SerialResult(True, "send", data={
            "id": cid, "sent": data.hex(" ").upper(),
            "sent_bytes": written,
            "received": response.hex(" ").upper() if response else "",
            "received_bytes": len(response),
        })
        log_serial("send", port="", data=result.data)
        if response:
            log_serial("recv", port="", data={
                "hex": response.hex(" ").upper(), "bytes": len(response),
            })
        if disconnect_reason:
            result.data["warning"] = f"disconnected: {disconnect_reason}"
        return result
    except Exception as e:
        log_serial("send", port="", success=False, error=str(e),
                   data={"id": cid, "reason": str(e)})
        return SerialResult(False, "send", error=str(e))


def serial_close(args: dict[str, Any]) -> SerialResult:
    """关闭串口。

    args: {id?}
    """
    cid = args.get("id", "default")
    t = _connections.pop(cid, None)
    if not t:
        return SerialResult(False, "close", error=f"not connected (id={cid})")
    try:
        t.close()
        result = SerialResult(True, "close", data={"id": cid, "status": "closed"})
        log_serial("close", port="", data=result.data)
        return result
    except Exception as e:
        log_serial("close", port="", success=False, error=str(e))
        return SerialResult(False, "close", error=str(e))


def serial_ports(args: dict[str, Any] | None = None) -> SerialResult:
    """列出可用串口。"""
    try:
        ports = SerialTransport.available_ports()
        connected = list(_connections.keys())
        return SerialResult(True, "ports", data={
            "available": ports, "connected": connected,
        })
    except Exception as e:
        return SerialResult(False, "ports", error=str(e))
