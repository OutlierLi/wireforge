"""WireForge 控制台 — Textual TUI。

用法: python3 -m console.tui
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Input, Static, TextArea
from textual.binding import Binding

from console.api import exec_cmd


# ── 参数解析 ──────────────────────────────────────────────────────────

def parse_options(tokens: list[str]) -> dict[str, str | list[str]]:
    """解析 --key value 和 --key=value 格式的参数。

    /decode --proto dlt645 --hex "FE FE 68 ... 16"
    → {"proto": "dlt645", "hex": "FE FE 68 ... 16"}
    """
    result: dict[str, str | list[str]] = {}
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise ValueError(f"unexpected argument: {token}")

        item = token[2:]

        if "=" in item:
            key, value = item.split("=", 1)
            index += 1
        elif index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
            key = item
            value = tokens[index + 1]
            index += 2
        else:
            key = item
            value = "true"
            index += 1

        if key in result:
            old = result[key]
            result[key] = old + [value] if isinstance(old, list) else [old, value]
        else:
            result[key] = value

    return result


# ── 历史输入框 ────────────────────────────────────────────────────────

class CmdInput(Input):
    """支持完整 ↑↓ 命令历史，并在回到最新位置时恢复原始输入。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: list[str] = []
        self._hindex: int = -1
        self._draft: str = ""

    def add_history(self, command: str) -> None:
        command = command.strip()
        if command and (not self._history or self._history[-1] != command):
            self._history.append(command)
        self._hindex = -1
        self._draft = ""

    def _set_history_value(self) -> None:
        self.value = self._history[self._hindex]
        self.cursor_position = len(self.value)

    def _on_key(self, event) -> None:
        if event.key == "up":
            if not self._history:
                return super()._on_key(event)

            if self._hindex == -1:
                self._draft = self.value
                self._hindex = len(self._history) - 1
            else:
                self._hindex = max(0, self._hindex - 1)

            self._set_history_value()
            event.prevent_default()
            event.stop()
            return

        if event.key == "down":
            if self._hindex == -1:
                return super()._on_key(event)

            if self._hindex < len(self._history) - 1:
                self._hindex += 1
                self._set_history_value()
            else:
                self._hindex = -1
                self.value = self._draft
                self.cursor_position = len(self.value)

            event.prevent_default()
            event.stop()
            return

        if event.key not in {
            "left", "right", "home", "end",
            "shift", "ctrl", "alt",
        }:
            self._hindex = -1

        return super()._on_key(event)


# ── App ───────────────────────────────────────────────────────────────

class WireForgeApp(App):
    """WireForge TUI — /build /decode /help /exit"""

    CSS = """
    Screen {
        background: #0b0f14;
        color: #c9d1d9;
        layout: vertical;
    }

    #topbar {
        height: 3;
        padding: 0 2;
        background: #161b22;
        color: #f0f6fc;
        border-bottom: solid #30363d;
        content-align: left middle;
        text-style: bold;
    }

    #output-panel {
        height: 1fr;
        margin: 1 1 0 1;
        background: #0d1117;
        border: round #30363d;
    }

    #output-title {
        height: 1;
        padding: 0 1;
        background: #161b22;
        color: #8b949e;
    }

    #output {
        height: 1fr;
        background: #0d1117;
        color: #c9d1d9;
        border: none;
        padding: 0 1;
    }

    #output .text-area--selection {
        background: #264f78;
    }

    #input-area {
        height: 3;
        margin: 1;
        padding: 0 1;
        background: #161b22;
        border: round #238636;
    }

    #prompt {
        width: 3;
        color: #3fb950;
        content-align: center middle;
        text-style: bold;
    }

    #cmd-input {
        width: 1fr;
        color: #f0f6fc;
        background: #161b22;
        border: none;
    }

    #cmd-input:focus { border: none; }

    #hint {
        height: 1;
        padding: 0 2;
        background: #161b22;
        color: #8b949e;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", show=False),
        Binding("ctrl+l", "clear_output", "清屏", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(
            " WIREFORGE  /  Protocol Console                         READY ",
            id="topbar",
        )

        with Vertical(id="output-panel"):
            yield Static(
                " OUTPUT  · Click to select  · Ctrl+C copy  · Tab returns to command",
                id="output-title",
            )
            output = TextArea("", id="output")
            output.read_only = True
            output.soft_wrap = True
            output.show_line_numbers = False
            yield output

        with Horizontal(id="input-area"):
            yield Static(" ▸ ", id="prompt")
            yield CmdInput(
                placeholder="/build /decode /help",
                id="cmd-input",
            )

        yield Static(
            " ↑↓ 历史  ·  Tab 切换输出区  ·  Ctrl+L 清屏  ·  Ctrl+Q 退出",
            id="hint",
        )

    def on_mount(self):
        self.write_output("WIREFORGE  —  /build /decode /help")
        self.query_one("#cmd-input", CmdInput).focus()

    # ── 输出 ──

    def write_output(self, text: str) -> None:
        output = self.query_one("#output", TextArea)
        follow_tail = output.scroll_y >= output.max_scroll_y - 1
        prefix = "\n" if output.text else ""
        output.insert(prefix + text.rstrip(), output.document.end)
        if follow_tail:
            output.scroll_end(animate=False)

    def action_clear_output(self):
        self.query_one("#output", TextArea).clear()

    # ── 输入 ──

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#cmd-input", CmdInput)
        if text:
            inp.add_history(text)
        inp.value = ""

        if not text:
            return

        self.write_output(f"❯ {text}")

        if text.startswith("/"):
            try:
                parts = shlex.split(text)
            except ValueError:
                parts = text.split()

            cmd = parts[0].lstrip("/")
            try:
                args_dict = parse_options(parts[1:])
            except ValueError as e:
                self.write_output(f"error: {e}")
                return

            result = exec_cmd(cmd, args_dict)

            if result.success:
                if result.path:
                    self.write_output(f"path: {result.path}")
                if result.frame_hex:
                    self.write_output(result.frame_hex)
                if result.structured:
                    _write_structured(self, result.structured)
                elif result.output:
                    _write(self, result.output, "")
            else:
                self.write_output(f"error: {result.error}")
                if result.path:
                    self.write_output(f"path: {result.path}")
                if result.structured:
                    _write_structured(self, result.structured)
                schema = (result.output or {}).get("input_schema", [])
                if schema:
                    self.write_output("input_schema:")
                    for f in schema:
                        req = "*" if f.get("required") else ""
                        vls = f" ({', '.join(str(v) for v in f['values'])})" if f.get("values") else ""
                        self.write_output(f"  {req}{f['name']}: {f['type']}{vls}")
                derived = (result.output or {}).get("derived_fields", {})
                if derived:
                    self.write_output(f"derived (auto): {list(derived.keys())}")
        elif text in ("help", "h"):
            self.write_output("commands:")
            self.write_output("  /build --proto dlt645 --func 0x11")
            self.write_output("  /build --proto dlt645 --func 0x11 --di 00010000 --dir uplink --resolve")
            self.write_output('  /decode --proto dlt645 --hex "FE FE 68 ... 16"')
        else:
            self.write_output("commands start with / — type 'help' for list")


def _write_structured(app: WireForgeApp, s: dict):
    """渲染结构化 wireforge.result/v1 JSON 到 TUI。"""
    # frame
    frame = s.get("frame", {})
    if frame:
        app.write_output("frame:")
        for k, v in frame.items():
            app.write_output(f"  {k}: {v}")

    # payload
    payload = s.get("payload", {})
    if payload:
        app.write_output("payload:")
        _write(app, payload, "  ")

    # wire.fields
    fields = s.get("wire", {}).get("fields", [])
    if fields:
        app.write_output("wire.fields:")
        for f in fields:
            off = f["offset"]
            app.write_output(f"  [{off[0]:>4},{off[1]:>4}) {f.get('path','?'):30s} {f.get('wire_hex',''):30s} → {f.get('value')}")

    # diagnostics
    diag = s.get("diagnostics", {})
    warns = diag.get("warnings", [])
    errs = diag.get("errors", [])
    for w in warns:
        app.write_output(f"  warn: {w}")
    for e in errs:
        app.write_output(f"  error: {e}")


def _write(app: WireForgeApp, obj, pfx: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                app.write_output(f"{pfx}{k}:")
                _write(app, v, pfx + "  ")
            else:
                app.write_output(f"{pfx}{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                _write(app, item, pfx)
            else:
                app.write_output(f"{pfx}- {item}")


def run():
    WireForgeApp().run()


if __name__ == "__main__":
    run()
