"""`/serial` 命令 — connect/open/close/set/disconnect 用 ``--name``；send 等选用连接用 ``--to``。"""

from __future__ import annotations

from typing import Any

from lab_service import get_lab_service
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
    args = _with_connection_name(args)
    if "port" not in args or not args["port"]:
        return missing_param("port", "str",
                             examples=["/dev/ttyUSB0", "COM3", "mock://loop"],
                             note="首次连接需指定完整参数")
    lab = get_lab_service()
    r = lab.open_serial(args)
    if r.success:
        _last_settings[_connection_name(args)] = _settings_from_args(args, r.data)
    return r.to_dict()


def _open(args: dict) -> dict:
    """重新打开指定连接的上次参数。"""
    args = _with_connection_name(args)
    target = _connection_name(args)
    lab = get_lab_service()
    settings = _last_settings.get(target) or lab.get_connection_settings(target)
    if not settings:
        settings = {"port": "mock://loop", "baudrate": 9600}
    lab.close_serial(args)
    open_args = {**settings, "to": target}
    r = lab.open_serial(open_args)
    if r.success:
        _last_settings[target] = _settings_from_args(open_args, r.data)
    return r.to_dict()


def _close(args: dict) -> dict:
    r = get_lab_service().close_serial(_with_connection_name(args))
    return r.to_dict()


def _send(args: dict) -> dict:
    args = _with_connection_target(args, auto_detect=True)
    if not args.get("to") and not get_lab_service().connection_id(args):
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

    r = get_lab_service().send_serial(args)
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
    args = _with_connection_name(args)
    target = _connection_name(args)
    current = _last_settings.get(target) or get_lab_service().get_connection_settings(target)
    if not current:
        current = {"port": "mock://loop", "baudrate": 9600, "bytesize": 8, "parity": "N"}

    new_params = {}
    for key in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout", "display"):
        if key in args:
            new_params[key] = args[key]
    if not new_params:
        return ok({
            "name": target,
            "to": target,
            "current": current,
            "hint": "use --baudrate 115200 --parity E to change",
        })

    current.update(new_params)
    _last_settings[target] = current
    log_config_change(target, new_params, current)
    return ok({
        "name": target,
        "to": target,
        "updated": new_params,
        "current": current,
        "hint": "参数已缓存。串口参数由 OS 驱动在 open 时初始化，已打开的串口无法热修改。请执行 /serial open 使新参数生效。",
    })


def _disconnect(args: dict) -> dict:
    r = get_lab_service().disconnect_serial(_with_connection_name(args))
    return r.to_dict()


def _ports(args: dict) -> dict:
    r = get_lab_service().serial_ports(args)
    return r.to_dict()


def _with_connection_name(args: dict, auto_detect: bool = False) -> dict:
    """管理类子命令：注册/选择连接名 ``--name``（兼容 conn/to/id）。"""
    normalized = dict(args)
    target = _pick_connection_key(normalized, ("name", "conn", "to", "id"))
    if not target:
        if auto_detect:
            target = get_lab_service().auto_detect_name()
        if not target:
            target = "default"
    normalized["to"] = target
    normalized["id"] = target
    normalized["name"] = target
    return normalized


def _with_connection_target(args: dict, auto_detect: bool = False) -> dict:
    """收发类子命令：选择已有连接 ``--to``（兼容 conn/id）。"""
    normalized = dict(args)
    target = _pick_connection_key(normalized, ("to", "conn", "id"))
    if not target and auto_detect:
        target = get_lab_service().auto_detect_name()
    if target:
        normalized["to"] = target
        normalized["id"] = target
    return normalized


def _pick_connection_key(args: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = args.get(key)
        if val not in (None, ""):
            return str(val)
    return ""


def _connection_name(args: dict) -> str:
    normalized = _with_connection_name(dict(args))
    return get_lab_service().connection_id(normalized) or "default"


def _to(args: dict) -> str:
    """send 等操作解析连接目标。"""
    normalized = _with_connection_target(dict(args))
    return get_lab_service().connection_id(normalized) or "default"


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
