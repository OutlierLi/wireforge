"""/serial 命令处理器 — 子命令模式: connect/open/close/send/set/disconnect/ports/use。

用法:
  /serial connect --port /dev/ttyUSB0 --baudrate 9600
  /serial connect --name cco --port /dev/ttyUSB0 --baudrate 9600
  /serial open
  /serial open --name cco
  /serial send --hex "68 ... 16"
  /serial send --name cco --hex "68 ... 16"
  /serial close --name cco
  /serial set --name cco --baudrate 115200
  /serial use --name cco
  /serial ports
"""

from __future__ import annotations

from typing import Any

from wireforge_serial.api import (
    active_connection,
    get_connection_settings,
    serial_close,
    serial_open,
    serial_ports,
    serial_send,
    serial_use,
)
from console.response import ok, fail, missing_param


def handle(args: dict[str, Any]) -> dict:
    sub = args.get("sub", "")
    if not sub:
        pos = args.get("_", [])
        sub = pos[0] if pos else "ports"

    cmd_map = {
        "connect": _connect, "open": _open, "close": _close,
        "send": _send, "set": _set, "disconnect": _disconnect,
        "ports": _ports, "list": _ports, "use": _use,
    }
    fn = cmd_map.get(sub)
    if not fn:
        return fail(f"unknown sub-command: {sub}. Available: {list(cmd_map.keys())}")
    return fn(args)


def _connect(args: dict) -> dict:
    """首次连接，必须指定串口参数。"""
    args = _with_connection_name(args)
    if "port" not in args or not args["port"]:
        return missing_param("port", "str",
                             examples=["/dev/ttyUSB0", "COM3", "mock://loop"],
                             note="首次连接需指定完整参数")
    r = serial_open(args)
    if r.success:
        _last_settings[_name(args)] = _settings_from_args(args, r.data)
    return r.to_dict()


def _open(args: dict) -> dict:
    """重新打开指定连接的上次参数。"""
    args = _with_connection_name(args)
    name = _name(args)
    settings = _last_settings.get(name) or get_connection_settings(name)
    if not settings:
        settings = {"port": "mock://loop", "baudrate": 9600}
    serial_close(args)
    open_args = {**settings, "name": name, "id": name}
    r = serial_open(open_args)
    if r.success:
        _last_settings[name] = _settings_from_args(open_args, r.data)
    return r.to_dict()


def _close(args: dict) -> dict:
    r = serial_close(_with_connection_name(args))
    return r.to_dict()


def _send(args: dict) -> dict:
    args = _with_connection_name(args, default_to_active=True)
    if "hex" not in args or not args["hex"]:
        return missing_param("hex", "str",
                             examples=["68 0C 00 40 03 01 01 03 00 E8 30 16"])
    r = serial_send(args)
    return r.to_dict()


def _set(args: dict) -> dict:
    """修改串口参数（需重连生效）。"""
    args = _with_connection_name(args)
    name = _name(args)
    current = _last_settings.get(name) or get_connection_settings(name)
    if not current:
        current = {"port": "mock://loop", "baudrate": 9600, "bytesize": 8, "parity": "N"}

    new_params = {}
    for key in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout", "display"):
        if key in args:
            new_params[key] = args[key]
    if not new_params:
        return ok({
            "name": name,
            "current": current,
            "hint": "use --baudrate 115200 --parity E to change",
        })

    current.update(new_params)
    _last_settings[name] = current
    return ok({
        "name": name,
        "updated": new_params,
        "current": current,
        "hint": "参数已缓存。串口参数由 OS 驱动在 open 时初始化，已打开的串口无法热修改。请执行 /serial open 使新参数生效。",
    })


def _disconnect(args: dict) -> dict:
    r = serial_close(_with_connection_name(args))
    return r.to_dict()


def _ports(args: dict) -> dict:
    r = serial_ports(args)
    return r.to_dict()


def _use(args: dict) -> dict:
    if "name" not in args and "id" not in args:
        return missing_param("name", "str", examples=["default", "cco", "sta1"])
    r = serial_use(_with_connection_name(args))
    return r.to_dict()


def _with_connection_name(args: dict, default_to_active: bool = False) -> dict:
    normalized = dict(args)
    if "name" in normalized and "id" not in normalized:
        normalized["id"] = normalized["name"]
    if "name" not in normalized and "id" not in normalized:
        normalized["name"] = active_connection() if default_to_active else "default"
        normalized["id"] = normalized["name"]
    if "name" not in normalized:
        normalized["name"] = normalized["id"]
    if "id" not in normalized:
        normalized["id"] = normalized["name"]
    return normalized


def _name(args: dict) -> str:
    return str(args.get("name") or args.get("id") or active_connection() or "default")


def _settings_from_args(args: dict, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    return {
        "port": args.get("port") or data.get("port") or "mock://loop",
        "baudrate": args.get("baudrate") or data.get("baudrate") or 9600,
        "bytesize": args.get("bytesize", 8),
        "parity": args.get("parity", "N"),
        "stopbits": args.get("stopbits", 1.0),
        "timeout": args.get("timeout", 0.05),
        "display": args.get("display", data.get("display", "hex")),
    }


# 按连接名缓存下一次 /serial open 使用的参数。
_last_settings: dict[str, dict[str, Any]] = {}
