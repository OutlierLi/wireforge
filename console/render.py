"""命令行渲染模块 — RichLog 彩色输出 + 文本可选中。

颜色标记通过 RichLog markup 实现: [color]text[/]。
主题从 console/theme.json 加载。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import RichLog

THEME = json.loads((Path(__file__).resolve().parent / "theme.json").read_text())
COLORS = THEME["colors"]
MARGIN = THEME["layout"]["margin"]

# Textual RichLog markup color mapping
_CLR = {
    "error":  "#f85149 bold",
    "warning": "#d2991d",
    "info":    "#58a6ff",
    "success": "#3fb950",
    "key":     "#79c0ff",
    "value":   "#c9d1d9",
    "text":    "#c9d1d9",
    "subtle":  "#6e7681",
    "frame":   "#3fb950",
    "path":    "#8b949e italic",
}


def _c(role: str) -> str:
    return _CLR.get(role, "#c9d1d9")


def _m() -> str:
    return " " * MARGIN


def render_result(out: RichLog, result: dict):
    """渲染 handler dict 到 RichLog，带颜色标记。"""
    status = result.get("status")
    if status == "success":
        data = result.get("data", {})
        if data.get("path"):
            out.write(f"[{_c('path')}]{_m()}{data['path']}[/]")
        if data.get("frame"):
            out.write(f"[{_c('frame')}]{_m()}{data['frame']}[/]")
        for k, v in data.items():
            if k in ("path", "frame"):
                continue
            _kv(out, k, v, 0)
    elif status == "need_input":
        out.write(f"[{_c('warning')}]{_m()}need input[/]")
        _render_missing(out, result.get("input_schema", []))
        if result.get("hint"):
            out.write(f"[{_c('subtle')}]{_m()}{result['hint']}[/]")
    elif status == "need_disambiguation":
        key = result.get("key", "")
        out.write(f"[{_c('warning')}]{_m()}need disambiguation {key}[/]")
        for c in result.get("candidates", []):
            out.write(f"[{_c('key')}]{_m()}  {c.get('label') or c.get('value')}[/]")
    elif status in {"no_route", "invalid_argument", "execution_error", "session_closed"}:
        err = result.get("error", status)
        out.write(f"[{_c('error')}]{_m()}{status}: {err}[/]")
        if result.get("path"):
            out.write(f"[{_c('path')}]{_m()}{result['path']}[/]")
        detail = result.get("detail", {})
        _render_missing(out, detail.get("missing", []))
        if detail.get("hint"):
            out.write(f"[{_c('subtle')}]{_m()}{detail['hint']}[/]")
    else:
        err = result.get("error", "unknown")
        out.write(f"[{_c('error')}]{_m()}error: {err}[/]")

        detail = result.get("detail", {})
        _render_missing(out, detail.get("missing", []))

        hint = detail.get("hint", "")
        if hint:
            out.write(f"[{_c('subtle')}]{_m()}{hint}[/]")


def _render_missing(out: RichLog, missing: list[dict]) -> None:
    if not missing:
        return
    out.write(f"[{_c('warning')}]{_m()}missing:[/]")
    for m in missing:
        examples = m.get("examples") or ([m.get("example")] if m.get("example") else [])
        eg = f"  e.g. {', '.join(str(e) for e in examples[:3])}" if examples else ""
        key = m.get("key") or m.get("name", "")
        out.write(f"[{_c('key')}]{_m()}  --{key}[/][{_c('text')}]: {m.get('type','')}{eg}[/]")
        if m.get("note"):
            out.write(f"[{_c('subtle')}]{_m()}    {m['note']}[/]")


def _kv(out: RichLog, key: str, value: Any, depth: int):
    indent = _m() + "  " * depth
    if isinstance(value, dict):
        out.write(f"[{_c('key')}]{indent}{key}:[/]")
        for k, v in value.items():
            _kv(out, k, v, depth + 1)
    elif isinstance(value, list):
        out.write(f"[{_c('key')}]{indent}{key}:[/]")
        for item in value:
            if isinstance(item, dict):
                _kv(out, "", item, depth + 1)
            else:
                out.write(f"[{_c('value')}]{indent}  - {item}[/]")
    else:
        out.write(f"[{_c('key')}]{indent}{key}:[/] [{_c('value')}]{value}[/]")
