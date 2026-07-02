"""In-process Lab Service.

This is the single owner boundary for hardware-facing operations in v1.5. The
implementation still runs in the CLI/MCP process, but upper layers call Lab
instead of importing the serial runtime directly. A future labd RPC process can
replace this module without changing command handlers.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from wireforge_serial.transport import SerialTransport

ROOT = Path(__file__).resolve().parent.parent
LAB_LOG_DIR = ROOT / "log" / "labd"
LAB_EVENTS = LAB_LOG_DIR / "events.log"

RxCallback = Callable[[bytes], None]


@dataclass
class LabEvent:
    type: str
    connection: str = ""
    port: str = ""
    hex: str = ""
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "type": self.type,
        }
        if self.connection:
            out["connection"] = self.connection
        if self.port:
            out["port"] = self.port
        if self.hex:
            out["hex"] = self.hex
        if self.detail:
            out["detail"] = self.detail
        return out


class LabService:
    """Hardware-facing service facade used by CLI, /run and MCP adapters."""

    def __init__(self) -> None:
        self._event_seq = 0
        self._events: list[dict[str, Any]] = []
        self._event_cv = threading.Condition()

    def open_serial(self, args: dict[str, Any]):
        from wireforge_serial.api import serial_open

        result = serial_open(args)
        data = result.data if getattr(result, "success", False) else {}
        connection = str(data.get("to") or data.get("id") or args.get("to") or args.get("name") or args.get("id") or "")
        transport = self.get_connection(connection) if connection else None
        if transport:
            self._wrap_rx(transport, connection)
        self.emit(LabEvent(
            "serial_open" if result.success else "serial_open_failed",
            connection=connection,
            port=str(data.get("port") or args.get("port") or ""),
            detail={"success": result.success, "error": result.error} if result.error else {"success": result.success},
        ))
        return result

    def send_serial(self, args: dict[str, Any]):
        from wireforge_serial.api import _connection_id, _normalize_args, serial_send

        normalized = _normalize_args(args)
        connection = _connection_id(normalized) or "default"
        result = serial_send(normalized)
        data = result.data if getattr(result, "success", False) else {}
        sent = str(data.get("sent") or normalized.get("hex") or "")
        self.emit(LabEvent(
            "serial_tx" if result.success else "serial_tx_failed",
            connection=connection,
            hex=sent,
            detail={"success": result.success, "sent_bytes": data.get("sent_bytes"), "error": result.error},
        ))
        return result

    def close_serial(self, args: dict[str, Any]):
        from wireforge_serial.api import _connection_id, _normalize_args, serial_close

        normalized = _normalize_args(args)
        connection = _connection_id(normalized) or "default"
        result = serial_close(normalized)
        self.emit(LabEvent(
            "serial_close" if result.success else "serial_close_failed",
            connection=connection,
            detail={"success": result.success, "error": result.error} if result.error else {"success": result.success},
        ))
        return result

    def disconnect_serial(self, args: dict[str, Any]):
        from wireforge_serial.api import _connection_id, _normalize_args, serial_disconnect

        normalized = _normalize_args(args)
        connection = _connection_id(normalized) or "default"
        result = serial_disconnect(normalized)
        self.emit(LabEvent(
            "serial_disconnect" if result.success else "serial_disconnect_failed",
            connection=connection,
            detail={"success": result.success, "error": result.error} if result.error else {"success": result.success},
        ))
        return result

    def serial_ports(self, args: dict[str, Any] | None = None):
        from wireforge_serial.api import serial_ports

        result = serial_ports(args)
        self.emit(LabEvent(
            "serial_ports",
            detail={
                "success": result.success,
                "connections": (result.data or {}).get("connected", []) if result.success else [],
                "error": result.error,
            },
        ))
        return result

    def get_connection(self, name: str | None = None) -> SerialTransport | None:
        from wireforge_serial.api import get_connection

        transport = get_connection(name)
        if transport and name:
            self._wrap_rx(transport, name)
        return transport

    def list_connected_names(self) -> list[str]:
        from wireforge_serial.api import list_connected_names

        return list_connected_names()

    def get_connection_settings(self, name: str) -> dict[str, Any] | None:
        from wireforge_serial.api import get_connection_settings

        return get_connection_settings(name)

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        from wireforge_serial.api import _normalize_args

        return _normalize_args(args)

    def connection_id(self, args: dict[str, Any]) -> str:
        from wireforge_serial.api import _connection_id

        return _connection_id(args)

    def auto_detect_name(self) -> str | None:
        from wireforge_serial.api import _auto_detect_name

        return _auto_detect_name()

    def bind_rx_display(self, transport: SerialTransport, connection: str) -> None:
        from wireforge_serial.api import bind_rx_display

        bind_rx_display(transport, connection)
        self._wrap_rx(transport, connection)

    def bind_rx_quiet(self, transport: SerialTransport, connection: str) -> None:
        from wireforge_serial.api import bind_rx_quiet

        bind_rx_quiet(transport, connection)
        self._wrap_rx(transport, connection)

    def write_with_tx_display(self, transport: SerialTransport, connection: str, data: bytes) -> int:
        from wireforge_serial.api import write_with_tx_display

        written = write_with_tx_display(transport, connection, data)
        self.emit(LabEvent("serial_tx", connection=connection, hex=data.hex(" ").upper(), detail={"sent_bytes": written}))
        return written

    def write_quiet(self, transport: SerialTransport, connection: str, data: bytes) -> int:
        from wireforge_serial.api import write_quiet

        written = write_quiet(transport, connection, data)
        self.emit(LabEvent("serial_tx", connection=connection, hex=data.hex(" ").upper(), detail={"sent_bytes": written, "display": "quiet"}))
        return written

    def emit(self, event: LabEvent) -> None:
        payload = event.to_dict()
        with self._event_cv:
            self._event_seq += 1
            payload["seq"] = self._event_seq
            self._events.append(payload)
            if len(self._events) > 2000:
                self._events = self._events[-1000:]
            self._event_cv.notify_all()
        LAB_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LAB_EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def event_cursor(self) -> int:
        with self._event_cv:
            return self._event_seq

    def events_since(self, seq: int = 0, *, limit: int = 100, timeout_ms: int = 0) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 500))
        timeout = max(0.0, float(timeout_ms or 0) / 1000.0)
        with self._event_cv:
            if timeout and self._event_seq <= seq:
                self._event_cv.wait(timeout=timeout)
            events = [event for event in self._events if int(event.get("seq") or 0) > seq]
            events = events[:limit]
            next_seq = int(events[-1].get("seq")) if events else self._event_seq
            return {"events": events, "next_seq": next_seq}

    def _wrap_rx(self, transport: SerialTransport, connection: str) -> None:
        current = getattr(transport, "on_rx_chunk", None)
        existing_wrapper = _lab_rx_wrapper(transport)
        if getattr(transport, "_lab_rx_wrapped_for", None) == connection and current is existing_wrapper:
            return
        if current is not None and current is not existing_wrapper:
            setattr(transport, "_lab_inner_rx", current)

        def wrapped(data: bytes) -> None:
            self.emit(LabEvent("serial_rx", connection=connection, hex=data.hex(" ").upper(), detail={"rx_bytes": len(data)}))
            callback = getattr(transport, "_lab_inner_rx", None)
            if callback:
                callback(data)

        setattr(transport, "_lab_rx_wrapper", wrapped)
        setattr(transport, "_lab_rx_wrapped_for", connection)
        transport.on_rx_chunk = wrapped


def _lab_rx_wrapper(transport: SerialTransport) -> RxCallback | None:
    wrapper = getattr(transport, "_lab_rx_wrapper", None)
    return wrapper if callable(wrapper) else None


_SERVICE: LabService | None = None


def get_lab_service() -> LabService:
    global _SERVICE
    if _SERVICE is None:
        if _rpc_enabled():
            from lab_service.rpc import DEFAULT_HOST, DEFAULT_PORT, RpcLabClient

            host, port = _rpc_endpoint()
            _SERVICE = RpcLabClient(host or DEFAULT_HOST, port or DEFAULT_PORT)  # type: ignore[assignment]
        else:
            _SERVICE = LabService()
    return _SERVICE


def _rpc_enabled() -> bool:
    value = str(os.environ.get("WIREFORGE_LABD_RPC") or "").strip().lower()
    return bool(os.environ.get("WIREFORGE_LABD_URL")) or value in {"1", "true", "yes", "on"}


def _rpc_endpoint() -> tuple[str | None, int | None]:
    raw = str(os.environ.get("WIREFORGE_LABD_URL") or "").strip()
    if raw.startswith("tcp://"):
        raw = raw[len("tcp://"):]
    if raw and ":" in raw:
        host, port = raw.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return host, None
    port_raw = os.environ.get("WIREFORGE_LABD_PORT")
    try:
        port = int(port_raw) if port_raw else None
    except ValueError:
        port = None
    host = os.environ.get("WIREFORGE_LABD_HOST")
    return host, port
