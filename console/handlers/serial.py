"""串口命令处理器 — 每个函数返回 dict。"""

from __future__ import annotations

from typing import Any

from serial.api import serial_open, serial_send, serial_close, serial_ports


def open(args: dict[str, Any]) -> dict:
    """打开串口。缺少 port 时返回结构化错误。"""
    if "port" not in args or not args["port"]:
        return {
            "success": False,
            "error": "missing required parameter",
            "detail": {
                "missing": [{"key": "port", "type": "str", "example": "/dev/ttyUSB0"}],
            },
        }
    r = serial_open(args)
    return r.to_dict()


def send(args: dict[str, Any]) -> dict:
    if "hex" not in args or not args["hex"]:
        return {
            "success": False,
            "error": "missing required parameter",
            "detail": {
                "missing": [{"key": "hex", "type": "str", "example": "68 0C 00 40 03 01 01 03 00 E8 30 16"}],
            },
        }
    r = serial_send(args)
    return r.to_dict()


def close(args: dict[str, Any]) -> dict:
    r = serial_close(args)
    return r.to_dict()


def ports(args: dict[str, Any]) -> dict:
    r = serial_ports(args)
    return r.to_dict()
