"""JSON-lines RPC transport for the persistent WireForge labd service."""

from __future__ import annotations

import argparse
import json
import socket
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Any

from lab_service.service import LabService

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass
class RpcResult:
    success: bool
    operation: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RpcResult":
        return cls(
            success=bool(payload.get("success")),
            operation=str(payload.get("operation") or ""),
            data=dict(payload.get("data") or {}),
            error=str(payload.get("error") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"success": self.success, "operation": self.operation}
        if self.data:
            out["data"] = self.data
        if self.error:
            out["error"] = self.error
        return out


class RpcSerialTransport:
    """Small transport proxy used by wait-frame/request/upg over labd RPC."""

    def __init__(self, client: "RpcLabClient", connection: str):
        self.client = client
        self.connection = connection

    @property
    def connected(self) -> bool:
        return bool(self.client.call("has_connection", {"name": self.connection}).get("connected"))

    def read_response(self, timeout: float, *, idle_timeout: float = 0.05) -> bytes:
        payload = self.client.call(
            "read_response",
            {"name": self.connection, "timeout": timeout, "idle_timeout": idle_timeout},
        )
        return bytes.fromhex(str(payload.get("hex") or ""))

    def prepend_rx(self, data: bytes) -> None:
        self.client.call("prepend_rx", {"name": self.connection, "hex": data.hex(" ").upper()})

    def write(self, data: bytes) -> int:
        payload = self.client.call(
            "write_with_tx_display",
            {"name": self.connection, "hex": data.hex(" ").upper()},
        )
        return int(payload.get("written") or 0)


class RpcLabClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout

    def open_serial(self, args: dict[str, Any]) -> RpcResult:
        return RpcResult.from_payload(self.call("open_serial", {"args": args}))

    def send_serial(self, args: dict[str, Any]) -> RpcResult:
        return RpcResult.from_payload(self.call("send_serial", {"args": args}))

    def close_serial(self, args: dict[str, Any]) -> RpcResult:
        return RpcResult.from_payload(self.call("close_serial", {"args": args}))

    def disconnect_serial(self, args: dict[str, Any]) -> RpcResult:
        return RpcResult.from_payload(self.call("disconnect_serial", {"args": args}))

    def serial_ports(self, args: dict[str, Any] | None = None) -> RpcResult:
        return RpcResult.from_payload(self.call("serial_ports", {"args": args or {}}))

    def get_connection(self, name: str | None = None) -> RpcSerialTransport | None:
        target = name or self.auto_detect_name()
        if not target:
            return None
        payload = self.call("has_connection", {"name": target})
        if not payload.get("connected"):
            return None
        return RpcSerialTransport(self, target)

    def list_connected_names(self) -> list[str]:
        payload = self.call("list_connected_names", {})
        names = payload.get("names")
        return [str(item) for item in names] if isinstance(names, list) else []

    def get_connection_settings(self, name: str) -> dict[str, Any] | None:
        payload = self.call("get_connection_settings", {"name": name})
        settings = payload.get("settings")
        return dict(settings) if isinstance(settings, dict) else None

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
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

    def connection_id(self, args: dict[str, Any]) -> str:
        explicit = args.get("to") or args.get("id")
        if explicit:
            return str(explicit)
        return self.auto_detect_name() or str(args.get("to") or args.get("id") or "")

    def auto_detect_name(self) -> str | None:
        payload = self.call("auto_detect_name", {})
        name = payload.get("name")
        return str(name) if name else None

    def bind_rx_display(self, transport: RpcSerialTransport, connection: str) -> None:
        self.call("bind_rx_display", {"name": connection})

    def bind_rx_quiet(self, transport: RpcSerialTransport, connection: str) -> None:
        self.call("bind_rx_quiet", {"name": connection})

    def write_with_tx_display(self, transport: RpcSerialTransport, connection: str, data: bytes) -> int:
        payload = self.call("write_with_tx_display", {"name": connection, "hex": data.hex(" ").upper()})
        return int(payload.get("written") or 0)

    def write_quiet(self, transport: RpcSerialTransport, connection: str, data: bytes) -> int:
        payload = self.call("write_quiet", {"name": connection, "hex": data.hex(" ").upper()})
        return int(payload.get("written") or 0)

    def ping(self) -> dict[str, Any]:
        return self.call("ping", {})

    def event_cursor(self) -> int:
        payload = self.call("event_cursor", {})
        return int(payload.get("seq") or 0)

    def events_since(self, seq: int = 0, *, limit: int = 100, timeout_ms: int = 0) -> dict[str, Any]:
        return self.call("events_since", {"seq": seq, "limit": limit, "timeout_ms": timeout_ms})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request = {"method": method, "params": params}
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                file = sock.makefile("rwb")
                file.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
                file.flush()
                line = file.readline()
        except OSError as exc:
            raise ConnectionError(f"labd RPC unavailable at {self.host}:{self.port}: {exc}") from exc
        if not line:
            raise ConnectionError("labd RPC closed without response")
        response = json.loads(line.decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or f"labd RPC failed: {method}"))
        data = response.get("data")
        return dict(data) if isinstance(data, dict) else {}


class LabRpcServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], service: LabService | None = None):
        super().__init__(server_address, LabRpcHandler)
        self.service = service or LabService()


class LabRpcHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline()
        if not raw:
            return
        try:
            request = json.loads(raw.decode("utf-8"))
            method = str(request.get("method") or "")
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            data = _dispatch(self.server.service, method, params)  # type: ignore[attr-defined]
            response = {"ok": True, "data": data}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")


def _dispatch(service: LabService, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {"pong": True}
    if method == "open_serial":
        return service.open_serial(dict(params.get("args") or {})).to_dict()
    if method == "send_serial":
        return service.send_serial(dict(params.get("args") or {})).to_dict()
    if method == "close_serial":
        return service.close_serial(dict(params.get("args") or {})).to_dict()
    if method == "disconnect_serial":
        return service.disconnect_serial(dict(params.get("args") or {})).to_dict()
    if method == "serial_ports":
        return service.serial_ports(dict(params.get("args") or {})).to_dict()
    if method == "event_cursor":
        return {"seq": service.event_cursor()}
    if method == "events_since":
        return service.events_since(
            int(params.get("seq") or 0),
            limit=int(params.get("limit") or 100),
            timeout_ms=int(params.get("timeout_ms") or 0),
        )
    if method == "list_connected_names":
        return {"names": service.list_connected_names()}
    if method == "get_connection_settings":
        return {"settings": service.get_connection_settings(str(params.get("name") or ""))}
    if method == "auto_detect_name":
        return {"name": service.auto_detect_name()}
    if method == "has_connection":
        name = str(params.get("name") or "")
        transport = service.get_connection(name)
        return {"connected": bool(transport and transport.connected)}
    if method == "bind_rx_display":
        name = str(params.get("name") or "")
        transport = _require_transport(service, name)
        service.bind_rx_display(transport, name)
        return {"ok": True}
    if method == "bind_rx_quiet":
        name = str(params.get("name") or "")
        transport = _require_transport(service, name)
        service.bind_rx_quiet(transport, name)
        return {"ok": True}
    if method == "write_with_tx_display":
        name, data = _name_and_bytes(params)
        transport = _require_transport(service, name)
        return {"written": service.write_with_tx_display(transport, name, data)}
    if method == "write_quiet":
        name, data = _name_and_bytes(params)
        transport = _require_transport(service, name)
        return {"written": service.write_quiet(transport, name, data)}
    if method == "read_response":
        name = str(params.get("name") or "")
        timeout = float(params.get("timeout") or 0)
        idle_timeout = float(params.get("idle_timeout") or 0.05)
        transport = _require_transport(service, name)
        data = transport.read_response(timeout, idle_timeout=idle_timeout)
        return {"hex": data.hex(" ").upper(), "rx_bytes": len(data)}
    if method == "prepend_rx":
        name, data = _name_and_bytes(params)
        transport = _require_transport(service, name)
        transport.prepend_rx(data)
        return {"ok": True}
    raise ValueError(f"unknown labd method: {method}")


def _require_transport(service: LabService, name: str):
    transport = service.get_connection(name)
    if not transport:
        raise RuntimeError(f"serial not connected (to={name})")
    return transport


def _name_and_bytes(params: dict[str, Any]) -> tuple[str, bytes]:
    name = str(params.get("name") or "")
    hex_str = str(params.get("hex") or "").replace(" ", "").replace("\n", "")
    if not name:
        raise ValueError("name is required")
    if not hex_str:
        raise ValueError("hex is required")
    return name, bytes.fromhex(hex_str)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, ready_event: threading.Event | None = None) -> None:
    with LabRpcServer((host, int(port))) as server:
        if ready_event:
            ready_event.set()
        server.serve_forever(poll_interval=0.2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WireForge persistent Lab daemon")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    print(f"wireforge labd listening on {args.host}:{args.port}", flush=True)
    try:
        serve(args.host, args.port)
    except KeyboardInterrupt:
        print("\nwireforge labd stopped", flush=True)
    return 0
