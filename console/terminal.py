"""Plain terminal console for WireForge.

It stays in the normal terminal buffer, uses line input, and falls back cleanly
when prompt_toolkit is not installed.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from console.api import complete_cmd, exec_text
from console.display import render_response


HISTORY_FILE = Path(__file__).resolve().parent.parent / "log" / ".wireforge_terminal_history"


def run_terminal(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the interactive plain terminal."""

    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    err = stderr or sys.stderr

    out.write("WireForge terminal, type /help or /exit\n")
    try:
        if _can_use_prompt_toolkit(inp):
            return _run_prompt_toolkit_terminal(out, err)
        return _run_plain_terminal(inp, out, err)
    except KeyboardInterrupt:
        out.write("\n")
        return 0


def _run_prompt_toolkit_terminal(stdout: TextIO, stderr: TextIO) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory

    class WireForgeCompleter(Completer):
        def get_completions(self, document: Any, complete_event: Any) -> Iterable[Completion]:
            text = document.text_before_cursor
            for value, start_position, label in _completion_candidates(text):
                yield Completion(value, start_position=start_position, display=label)

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        completer=WireForgeCompleter(),
        complete_while_typing=True,
    )

    while True:
        try:
            line = session.prompt("wireforge> ")
        except EOFError:
            stdout.write("\n")
            return 0
        except KeyboardInterrupt:
            stdout.write("\n")
            continue
        if _should_exit(line):
            return 0
        _execute_line(line, stdout, stderr)


def _run_plain_terminal(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    stdout.write("prompt_toolkit not available; using plain input mode.\n")
    while True:
        stdout.write("wireforge> ")
        stdout.flush()
        line = stdin.readline()
        if not line:
            return 0
        if _should_exit(line):
            return 0
        _execute_line(line, stdout, stderr)


def _execute_line(line: str, stdout: TextIO, stderr: TextIO) -> None:
    text = line.strip()
    if not text:
        return
    try:
        response = exec_text(text if text.startswith("/") else f"/{text}")
        render_response(text, response, stdout)
    except Exception as exc:
        stderr.write(f"error: {exc}\n")


def _completion_candidates(text: str) -> list[tuple[str, int, str]]:
    response = complete_cmd(text=text)
    data = response.get("data") or {}
    start = int(data.get("start_position", 0))
    items: list[tuple[str, int, str]] = []
    for item in data.get("completions", []):
        value = str(item.get("value") or item.get("label") or "")
        if not value:
            continue
        label = str(item.get("label") or value)
        items.append((value, start, label))
    return items


def _can_use_prompt_toolkit(stdin: TextIO) -> bool:
    if not stdin.isatty():
        return False
    try:
        import prompt_toolkit  # noqa: F401
    except Exception:
        return False
    return True


def _should_exit(line: str) -> bool:
    return line.strip() in {"/exit", "/quit", "exit", "quit"}


def main(argv: list[str] | None = None) -> int:
    return run_terminal()


if __name__ == "__main__":
    raise SystemExit(main())
