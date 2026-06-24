"""串口命令处理器 — 返回统一格式 dict。"""

from __future__ import annotations

from typing import Any

from serial.api import serial_open, serial_send, serial_close, serial_ports
from console.response import missing_param


def open(args: dict[str, Any]) -> dict:
    if "port" not in args or not args["port"]:
        return missing_param("port", "str",
                             examples=["mock://loop", "virtual://demo",
                                       "/dev/ttyUSB0", "COM3"],
                             note="mock=内存回环, virtual=跨进程总线, 其他=物理串口")
    r = serial_open(args)
    return r.to_dict()


def send(args: dict[str, Any]) -> dict:
    if "hex" not in args or not args["hex"]:
        return missing_param("hex", "str",
                             examples=["68 0C 00 40 03 01 01 03 00 E8 30 16"])
    r = serial_send(args)
    return r.to_dict()


def close(args: dict[str, Any]) -> dict:
    r = serial_close(args)
    return r.to_dict()


def ports(args: dict[str, Any]) -> dict:
    r = serial_ports(args)
    return r.to_dict()
