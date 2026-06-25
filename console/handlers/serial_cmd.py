"""/serial 命令处理器 — 子命令模式: connect/open/close/send/set/disconnect/ports。

用法:
  /serial connect --port /dev/ttyUSB0 --baudrate 9600
  /serial open
  /serial send --hex "68 ... 16"
  /serial close
  /serial set --baudrate 115200
  /serial disconnect
  /serial ports
"""

from __future__ import annotations

from typing import Any

from serial.api import serial_open, serial_send, serial_close, serial_ports
from serial.transport import SerialTransport, SerialSettings
from console.response import ok, fail, missing_param


def handle(args: dict[str, Any]) -> dict:
    sub = args.get("sub", "")
    if not sub:
        pos = args.get("_", [])
        sub = pos[0] if pos else "ports"

    cmd_map = {
        "connect": _connect, "open": _open, "close": _close,
        "send": _send, "set": _set, "disconnect": _disconnect,
        "ports": _ports, "list": _ports,
    }
    fn = cmd_map.get(sub)
    if not fn:
        return fail(f"unknown sub-command: {sub}. Available: {list(cmd_map.keys())}")
    return fn(args)


def _connect(args: dict) -> dict:
    """首次连接，必须指定串口参数。"""
    if "port" not in args or not args["port"]:
        return missing_param("port", "str",
                             examples=["/dev/ttyUSB0", "COM3", "mock://loop"],
                             note="首次连接需指定完整参数")
    r = serial_open(args)
    return r.to_dict()


def _open(args: dict) -> dict:
    """重新打开上次连接。"""
    r = serial_close({})
    r = serial_open({"port": _last_port or "mock://loop",
                     "baudrate": _last_settings.get("baudrate", 9600) if _last_settings else 9600})
    return r.to_dict()


def _close(args: dict) -> dict:
    r = serial_close(args)
    return r.to_dict()


def _send(args: dict) -> dict:
    if "hex" not in args or not args["hex"]:
        return missing_param("hex", "str",
                             examples=["68 0C 00 40 03 01 01 03 00 E8 30 16"])
    r = serial_send(args)
    return r.to_dict()


def _set(args: dict) -> dict:
    """修改串口参数（需重连生效）。"""
    global _last_settings
    if not _last_settings:
        import json
        from serial.api import _connections
        t = _connections.get("default")
        if t:
            _last_settings = t.settings.to_dict()
        else:
            _last_settings = {"port": "mock://loop", "baudrate": 9600, "bytesize": 8, "parity": "N"}

    new_params = {}
    for key in ("baudrate", "bytesize", "parity", "stopbits"):
        if key in args:
            new_params[key] = args[key]
    if not new_params:
        return ok({"current": _last_settings, "hint": "use --baudrate 115200 --parity E to change"})

    _last_settings.update(new_params)
    return ok({
        "updated": new_params,
        "hint": "参数已缓存。串口参数由 OS 驱动在 open 时初始化，已打开的串口无法热修改。请执行 /serial open 使新参数生效。",
    })


def _disconnect(args: dict) -> dict:
    r = serial_close(args)
    return r.to_dict()


def _ports(args: dict) -> dict:
    r = serial_ports(args)
    return r.to_dict()


# 状态缓存
_last_port: str = ""
_last_settings: dict[str, Any] | None = None
