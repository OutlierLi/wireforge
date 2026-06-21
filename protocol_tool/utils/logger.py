"""运行时日志 — 分行记录所有 Build 和 Decode 操作。

日志位置: log/build.log, log/decode.log
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"


def _ensure():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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
    return obj
