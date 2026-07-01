"""`/serial` 命令 — connect/open/close/send/set/disconnect/ports；连接目标用 ``--to``。"""

from __future__ import annotations

from typing import Any

from wireforge_serial.api import (
    _auto_detect_name,
    _connection_id,
    _normalize_args,
    get_connection_settings,
    serial_close,
    serial_open,
    serial_ports,
    serial_send,
)
from wireforge_serial.logger import log_config_change
from console.response import ok, fail, missing_param

_SERIAL_SEND_BUILD_RESERVED = frozenset({
    "build", "hex", "to", "conn", "name", "id",
})


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
    args = _with_connection_to(args)
    if "port" not in args or not args["port"]:
        return missing_param("port", "str",
                             examples=["/dev/ttyUSB0", "COM3", "mock://loop"],
                             note="首次连接需指定完整参数")
    r = serial_open(args)
    if r.success:
        _last_settings[_to(args)] = _settings_from_args(args, r.data)
    return r.to_dict()


def _open(args: dict) -> dict:
    """重新打开指定连接的上次参数。"""
    args = _with_connection_to(args)
    target = _to(args)
    settings = _last_settings.get(target) or get_connection_settings(target)
    if not settings:
        settings = {"port": "mock://loop", "baudrate": 9600}
    serial_close(args)
    open_args = {**settings, "to": target}
    r = serial_open(open_args)
    if r.success:
        _last_settings[target] = _settings_from_args(open_args, r.data)
    return r.to_dict()


def _close(args: dict) -> dict:
    r = serial_close(_with_connection_to(args))
    return r.to_dict()


def _send(args: dict) -> dict:
    args = _with_connection_to(args, auto_detect=True)
    if not args.get("to") and not _connection_id(args):
        return fail("multiple serial connections active — specify --to",
                    detail={"hint": "use /serial ports to list connections"})

    build_info: dict[str, Any] | None = None
    if args.get("build"):
        from console.handlers.build import build_frame_from_args

        build_result = build_frame_from_args(
            args, extra_reserved=_SERIAL_SEND_BUILD_RESERVED,
        )
        if not build_result.get("success"):
            detail = build_result.get("detail")
            err = build_result.get("error", "build failed")
            if build_result.get("status") == "route_required":
                return fail(err, detail=detail)
            return fail(err, detail=detail)
        build_info = build_result.get("data") or {}
        args = {**args, "hex": build_info.get("frame", "")}
    elif "hex" not in args or not args["hex"]:
        return missing_param(
            "hex", "str",
            examples=["68 0C 00 40 03 01 01 03 00 E8 30 16"],
            note="或使用 --build --proto csg --afn ... 由路由构造报文",
        )

    r = serial_send(args)
    out = r.to_dict()
    if build_info and out.get("success"):
        data = dict(out.get("data") or {})
        data["built"] = {
            "path": build_info.get("path"),
            "frame": build_info.get("frame"),
            "resolved": build_info.get("resolved"),
        }
        out["data"] = data
    return out


def _set(args: dict) -> dict:
    """修改串口参数（需重连生效）。"""
    args = _with_connection_to(args)
    target = _to(args)
    current = _last_settings.get(target) or get_connection_settings(target)
    if not current:
        current = {"port": "mock://loop", "baudrate": 9600, "bytesize": 8, "parity": "N"}

    new_params = {}
    for key in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout", "display"):
        if key in args:
            new_params[key] = args[key]
    if not new_params:
        return ok({
            "to": target,
            "current": current,
            "hint": "use --baudrate 115200 --parity E to change",
        })

    current.update(new_params)
    _last_settings[target] = current
    log_config_change(target, new_params, current)
    return ok({
        "to": target,
        "updated": new_params,
        "current": current,
        "hint": "参数已缓存。串口参数由 OS 驱动在 open 时初始化，已打开的串口无法热修改。请执行 /serial open 使新参数生效。",
    })


def _disconnect(args: dict) -> dict:
    r = serial_close(_with_connection_to(args))
    return r.to_dict()


def _ports(args: dict) -> dict:
    r = serial_ports(args)
    return r.to_dict()


def _with_connection_to(args: dict, auto_detect: bool = False) -> dict:
    """规范化连接目标 ``to``（兼容 conn/name/id 别名）。"""
    normalized = _normalize_args(dict(args))
    if not normalized.get("to"):
        if auto_detect:
            detected = _auto_detect_name()
            if detected:
                normalized["to"] = detected
        else:
            normalized["to"] = "default"
    if normalized.get("to"):
        normalized["id"] = str(normalized["to"])
    return normalized


def _to(args: dict) -> str:
    normalized = _normalize_args(dict(args))
    return _connection_id(normalized) or "default"


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


_last_settings: dict[str, dict[str, Any]] = {}
