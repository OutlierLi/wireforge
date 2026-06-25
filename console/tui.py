"""WireForge 控制台 — Textual TUI with theme support。

用法: python3 -m console.tui
"""

from __future__ import annotations

import shlex, sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Input, Static, RichLog
from textual.binding import Binding

from console.api import exec_cmd
from console.render import render_result, COLORS, THEME

_layout = THEME["layout"]
MARGIN = _layout["margin"]
C = COLORS


class CmdInput(Input):
    """方向键上调历史记录。"""

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
        if event.key not in {"left", "right", "home", "end", "shift", "ctrl", "alt"}:
            self._hindex = -1
        return super()._on_key(event)


class WireForgeApp(App):
    """WireForge TUI。"""

    CSS = f"""
    Screen {{
        background: {C['bg']};
        color: {C['text']};
        layout: vertical;
    }}

    #topbar {{
        height: 3;
        padding: 0 {MARGIN};
        background: {C['input_bg']};
        color: {C['text']};
        border-bottom: solid {C['border']};
        content-align: left middle;
        text-style: bold;
    }}

    #output-panel {{
        height: 1fr;
        margin: 1 {MARGIN} 2 {MARGIN};
        background: {C['bg']};
        border: round {C['border']};
    }}

    #output-title {{
        height: 1;
        padding: 0 {MARGIN};
        background: {C['input_bg']};
        color: {C['subtle']};
    }}

    #output {{
        height: 1fr;
        background: {C['bg']};
        border: none;
        padding: 0 {MARGIN};
    }}

    #input-area {{
        height: {_layout['input_height']};
        margin: 2 {MARGIN} 1 {MARGIN};
        padding: 0 {MARGIN};
        background: {C['input_bg']};
        border: round {C['success']};
    }}

    #prompt {{
        width: 3;
        color: {C['success']};
        content-align: center middle;
        text-style: bold;
    }}

    #cmd-input {{
        width: 1fr;
        color: {C['text']};
        background: {C['input_bg']};
        border: none;
    }}

    #cmd-input:focus {{ border: none; }}

    #hint {{
        height: {_layout['hint_height']};
        padding: 0 {MARGIN};
        background: {C['input_bg']};
        color: {C['subtle']};
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", show=False),
        Binding("ctrl+l", "clear_output", "清屏", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(" WIREFORGE  /  Protocol Console                         READY ", id="topbar")

        with Vertical(id="output-panel"):
            yield Static(" OUTPUT ", id="output-title")
            yield RichLog(id="output", markup=True, wrap=True, highlight=True)

        with Horizontal(id="input-area"):
            yield Static(" ▸ ", id="prompt")
            yield CmdInput(placeholder="/help /build /decode /serial /auto_rule", id="cmd-input")

        yield Static(" ↑↓ history  ·  Ctrl+L clear  ·  Ctrl+Q quit", id="hint")

    def on_mount(self):
        out = self.query_one("#output", RichLog)
        out.write(f"[{C['subtle']}]{' '*MARGIN}WireForge — /help for commands[/]")
        self.query_one("#cmd-input", CmdInput).focus()

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#cmd-input", CmdInput)
        if text:
            inp.add_history(text)
        inp.value = ""

        if not text:
            return

        out = self.query_one("#output", RichLog)
        out.write(f"[{C['subtle']}]{' '*MARGIN}❯ {text}[/]")

        if text.startswith("/"):
            parts = shlex.split(text)
            cmd = parts[0].lstrip("/")
            args = {}
            for a in parts[1:]:
                if a.startswith("--"):
                    key = a.lstrip("-")
                    if "=" in key:
                        k, v = key.split("=", 1)
                        args[k] = v
                    else:
                        args[key] = "true"
                else:
                    # positional args
                    args.setdefault("_", []).append(a)

            result = exec_cmd(cmd, args)
            render_result(out, result)
        elif text in ("help", "h"):
            r = exec_cmd("help", {})
            render_result(out, r)
        else:
            out.write(f"[{C['subtle']}]{' '*MARGIN}commands start with / — type '/help' for list[/]")

    def action_clear_output(self):
        self.query_one("#output", RichLog).clear()


def run():
    WireForgeApp().run()


if __name__ == "__main__":
    run()
