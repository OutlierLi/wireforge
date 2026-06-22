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
from textual.widgets import Input, Static, RichLog
from textual.binding import Binding

from console.api import exec_cmd


class CmdInput(Input):
    """方向键上调历史记录的输入框。光标在首字符时 ↑ 调出上一条命令。"""

    _history: list[str] = []
    _hindex: int = -1

    def add_history(self, cmd: str):
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        self._hindex = -1

    def _on_key(self, event):
        if event.key == "up" and self.cursor_position == 0 and self._history:
            if self._hindex == -1:
                self._hindex = len(self._history) - 1
            elif self._hindex > 0:
                self._hindex -= 1
            self.value = self._history[self._hindex]
            self.cursor_position = len(self.value)
            event.prevent_default()
            event.stop()
            return
        elif event.key == "down" and self.cursor_position == len(self.value) and self._hindex != -1:
            if self._hindex < len(self._history) - 1:
                self._hindex += 1
                self.value = self._history[self._hindex]
            else:
                self._hindex = -1
                self.value = ""
            self.cursor_position = len(self.value)
            event.prevent_default()
            event.stop()
            return
        self._hindex = -1
        return super()._on_key(event)


class WireForgeApp(App):
    """WireForge TUI — /build /decode /help /exit"""

    CSS = """
    Screen { background: #0d1117; layout: vertical; }

    #output {
        background: #0d1117;
        border: none;
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    #input-area {
        background: #161b22;
        border-top: solid #30363d;
        padding: 0 1;
        height: 3;
    }

    #prompt {
        color: #3fb950;
        width: 3;
        content-align: center middle;
    }

    #cmd-input {
        background: #161b22;
        color: #c9d1d9;
        border: none;
        width: 1fr;
    }

    #cmd-input:focus { border: none; }

    #hint {
        background: #0d1117;
        color: #484f58;
        height: 1;
        padding: 0 1;
        content-align: left middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield RichLog(id="output", markup=True, wrap=True, highlight=True)

        with Container(id="input-area"):
            with Horizontal():
                yield Static(" ▸ ", id="prompt")
                yield CmdInput(placeholder="输入命令...", id="cmd-input")

        yield Static(" /build /decode /help  |  ↑↓ 历史  |  Ctrl+C 退出", id="hint")

    def on_mount(self):
        out = self.query_one("#output", RichLog)
        out.write("[#6e7681]WireForge — /build /decode /help[/]")
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
        out.write(f"[#6e7681]❯ {text}[/]")

        if text.startswith("/"):
            parts = shlex.split(text)
            cmd = parts[0].lstrip("/")
            args_list = parts[1:]
            args_dict = {}
            for a in args_list:
                if a.startswith("--"):
                    key = a.lstrip("-")
                    if "=" in key:
                        k, v = key.split("=", 1)
                        args_dict[k] = v
                    else:
                        args_dict[key] = "true"

            result = exec_cmd(cmd, args_dict)

            if result.success:
                if result.path:
                    out.write(f"[italic #58a6ff]{result.path}[/]")
                if result.frame_hex:
                    out.write(f"[bold #3fb950]{result.frame_hex}[/]")
                if result.output:
                    _write(out, result.output, "")
            else:
                out.write(f"[bold #f85149]error: {result.error}[/]")
                if result.path:
                    out.write(f"[#6e7681 italic]{result.path}[/]")
                schema = (result.output or {}).get("input_schema", [])
                if schema:
                    names = [f["name"] for f in schema]
                    out.write(f"[#d2991d]required: {', '.join(names)}[/]")
        elif text in ("help", "h"):
            out.write("[#6e7681]commands:[/]")
            out.write("  /build --proto dlt645 --func 0x11")
            out.write("  /decode --proto dlt645 --hex FE FE 68 ... 16")
        else:
            out.write("[#6e7681]commands start with / — type 'help' for list[/]")


def _write(out: RichLog, obj, pfx: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.write(f"[#c9d1d9]{pfx}{k}:[/]")
                _write(out, v, pfx + "  ")
            else:
                out.write(f"[#6e7681]{pfx}{k}:[/] [#c9d1d9]{v}[/]")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                _write(out, item, pfx)
            else:
                out.write(f"[#c9d1d9]{pfx}- {item}[/]")


def run():
    WireForgeApp().run()


if __name__ == "__main__":
    run()
