"""运行时日志 — 分行记录所有 Build, Decode 和 Console 操作。

日志位置: log/build.log, log/decode.log, log/console.log
格式:
  [BUILD] timestamp protocol=xxx
    info: {...}
    msg: xxx
    [PATH] ...
    [FRAME] ...
    [DEBUG] values: {...}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"


def _ensure():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + now.strftime("%z")


def log_build(protocol: str,
              info: dict[str, Any] | None = None,
              message_id: str | None = None,
              path: str | None = None,
              frame_hex: str = "",
              values: dict[str, Any] | None = None,
              success: bool = True,
              error: str = "") -> None:
    _ensure()
    tag = "[BUILD]"
    if not success:
        tag = "[BUILD][ERROR]"

    lines = [f"{tag} {_ts()}  protocol={protocol}"]

    if error:
        lines.append(f"  error: {error}")
    else:
        if info:
            lines.append(f"  info: {json.dumps(info, ensure_ascii=False)}")
        if message_id:
            lines.append(f"  msg: {message_id}")
    if path:
        lines.append(f"  [PATH] {path}")
    if frame_hex:
        lines.append(f"  [FRAME] {frame_hex}")
    if values:
        lines.append(f"  [DEBUG] values: {json.dumps(_simplify(values), ensure_ascii=False)}")

    with open(_LOG_DIR / "build.log", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def log_decode(protocol: str,
               frame_hex: str = "",
               path: str | None = None,
               values: dict[str, Any] | None = None,
               warnings: list[str] | None = None,
               success: bool = True,
               error: str = "") -> None:
    _ensure()
    tag = "[DECODE]"
    if not success:
        tag = "[DECODE][ERROR]"

    lines = [f"{tag} {_ts()}  protocol={protocol}"]

    if error:
        lines.append(f"  error: {error}")
    if frame_hex:
        lines.append(f"  [FRAME] {frame_hex}")
    if path:
        lines.append(f"  [PATH] {path}")
    if values:
        lines.append(f"  [DEBUG] values: {json.dumps(_simplify(values), ensure_ascii=False)}")
    if warnings:
        lines.append(f"  [DEBUG] warnings: {json.dumps(warnings, ensure_ascii=False)}")

    with open(_LOG_DIR / "decode.log", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def _simplify(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return obj.hex(" ").upper()
    if isinstance(obj, dict):
        return {k: _simplify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_simplify(i) for i in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        # 小整数用十六进制 (协议字段), 大整数保持十进制 (baudrate, bytes, seq 等)
        if 0 <= obj <= 255:
            return f"0x{obj:02X}"
        return obj
    return obj


# ── Console 日志 ──────────────────────────────────────────────────────

def log_console(command: str,
                args: dict[str, Any] | None = None,
                result: dict[str, Any] | None = None) -> None:
    """记录控制台命令调用 — 请求 + 响应 JSON。"""
    _ensure()
    success = bool(result and (result.get("success", False) or result.get("status") == "success"))
    tag = "[CONSOLE]" if success else "[CONSOLE][ERROR]"
    lines = [f"{tag} {_ts()}  cmd={command}"]
    if args:
        lines.append(f"  > {json.dumps(_simplify(args), ensure_ascii=False)}")
    if result:
        lines.append(f"  < {json.dumps(_simplify(result), ensure_ascii=False)}")
    with open(_LOG_DIR / "console.log", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


# ── Serial 日志 ───────────────────────────────────────────────────────

def log_serial(operation: str, port: str = "", data: dict[str, Any] | None = None,
               success: bool = True, error: str = "") -> None:
    """记录串口操作: open, close, send, recv。"""
    _ensure()
    tag = "[SERIAL]" if success else "[SERIAL][ERROR]"
    lines = [f"{tag} {_ts()}  op={operation}  port={port}"]
    if data:
        lines.append(f"  data: {json.dumps(_simplify(data), ensure_ascii=False)}")
    if error:
        lines.append(f"  error: {error}")
    with open(_LOG_DIR / "serial.log", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
