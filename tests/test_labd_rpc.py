from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator

import pytest

import lab_service.service as service_module
from console.api import exec_cmd
from lab_service.rpc import LabRpcServer, RpcLabClient


@pytest.fixture
def labd_server() -> Iterator[tuple[RpcLabClient, str]]:
    server = LabRpcServer(("127.0.0.1", 0))
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RpcLabClient(str(host), int(port))
    try:
        assert client.ping()["pong"] is True
        yield client, f"tcp://{host}:{port}"
    finally:
        try:
            client.close_serial({"to": "rpc"})
            client.close_serial({"to": "cmd_rpc"})
            client.disconnect_serial({"to": "rpc_a"})
            client.disconnect_serial({"to": "rpc_b"})
        except Exception:
            pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service_module._SERVICE = None


def test_rpc_client_serial_loopback(labd_server):
    client, _ = labd_server

    opened = client.open_serial({"to": "rpc", "port": "mock://loop"})
    assert opened.success, opened.to_dict()
    assert client.list_connected_names() == ["rpc"]

    sent = client.send_serial({"to": "rpc", "hex": "AA BB"})
    assert sent.success, sent.to_dict()
    transport = client.get_connection("rpc")
    assert transport is not None
    assert transport.read_response(1.0) == bytes.fromhex("AA BB")

    closed = client.close_serial({"to": "rpc"})
    assert closed.success, closed.to_dict()


def test_serial_command_uses_persistent_labd(monkeypatch, labd_server):
    client, url = labd_server
    monkeypatch.setenv("WIREFORGE_LABD_URL", url)
    service_module._SERVICE = None

    opened = exec_cmd("serial", {"sub": "connect", "name": "cmd_rpc", "port": "mock://loop"})
    assert opened["status"] == "success", opened
    assert client.list_connected_names() == ["cmd_rpc"]

    sent = exec_cmd("serial", {"sub": "send", "to": "cmd_rpc", "hex": "68 16"})
    assert sent["status"] == "success", sent
    assert sent["data"]["to"] == "cmd_rpc"

    ports = exec_cmd("serial", {"sub": "ports"})
    assert ports["status"] == "success", ports
    assert "cmd_rpc" in ports["data"]["connected"]

    closed = exec_cmd("serial", {"sub": "close", "name": "cmd_rpc"})
    assert closed["status"] == "success", closed


def test_rpc_virtual_bus_events_between_named_connections(labd_server):
    client, _ = labd_server
    bus = f"virtual://rpc_evt_{uuid.uuid4().hex}"

    assert client.open_serial({"to": "rpc_a", "port": bus}).success
    assert client.open_serial({"to": "rpc_b", "port": bus}).success
    seq = client.event_cursor()

    sent = client.send_serial({"to": "rpc_a", "hex": "AA BB CC"})
    assert sent.success, sent.to_dict()

    deadline = time.monotonic() + 2.0
    events = []
    while time.monotonic() < deadline:
        payload = client.events_since(seq, timeout_ms=250)
        seq = int(payload.get("next_seq") or seq)
        events.extend(payload.get("events") or [])
        if any(
            event.get("type") == "serial_rx"
            and event.get("connection") == "rpc_b"
            and event.get("hex") == "AA BB CC"
            for event in events
        ):
            break
    assert any(
        event.get("type") == "serial_rx"
        and event.get("connection") == "rpc_b"
        and event.get("hex") == "AA BB CC"
        for event in events
    ), events


def test_serial_disconnect_removes_connection_record(monkeypatch, labd_server):
    client, url = labd_server
    monkeypatch.setenv("WIREFORGE_LABD_URL", url)
    service_module._SERVICE = None

    opened = exec_cmd("serial", {"sub": "connect", "name": "cmd_rpc", "port": "mock://loop"})
    assert opened["status"] == "success", opened

    closed = exec_cmd("serial", {"sub": "close", "name": "cmd_rpc"})
    assert closed["status"] == "success", closed
    ports_after_close = exec_cmd("serial", {"sub": "ports"})
    assert any(item.get("to") == "cmd_rpc" for item in ports_after_close["data"].get("connections", []))

    reopened = exec_cmd("serial", {"sub": "open", "name": "cmd_rpc"})
    assert reopened["status"] == "success", reopened
    disconnected = exec_cmd("serial", {"sub": "disconnect", "name": "cmd_rpc"})
    assert disconnected["status"] == "success", disconnected

    ports_after_disconnect = exec_cmd("serial", {"sub": "ports"})
    assert not any(item.get("to") == "cmd_rpc" for item in ports_after_disconnect["data"].get("connections", []))
    assert "cmd_rpc" not in client.list_connected_names()
