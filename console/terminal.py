"""Plain terminal console for WireForge.

It stays in the normal terminal buffer, uses line input, and falls back cleanly
when prompt_toolkit is not installed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from console.api import complete_cmd, exec_text


_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = _ROOT / "log" / ".wireforge_terminal_history"


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
            start_position = _completion_start_position(text)
            for item in _completion_candidates(text):
                yield Completion(item, start_position=start_position)

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
        _render_response(response, stdout)
    except Exception as exc:
        stderr.write(f"error: {exc}\n")


def _render_response(response: dict[str, Any], stdout: TextIO) -> None:
    status = response.get("status", "error")
    if status == "success":
        data = response.get("data") or {}
        stdout.write("success\n")
        _render_value(data, stdout, 1)
        return

    if status == "need_input":
        stdout.write("need input\n")
        for item in response.get("input_schema", []):
            key = item.get("key") or item.get("name") or ""
            type_name = item.get("type", "str")
            examples = item.get("examples") or []
            suffix = f"  e.g. {', '.join(str(x) for x in examples[:3])}" if examples else ""
            stdout.write(f"  --{key}: {type_name}{suffix}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    if status == "need_disambiguation":
        stdout.write(f"need disambiguation {response.get('key', '')}\n")
        for item in response.get("candidates", []):
            stdout.write(f"  {item.get('label') or item.get('value')}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    error = response.get("error") or status
    stdout.write(f"{status}: {error}\n")
    detail = response.get("detail")
    if detail:
        _render_value(detail, stdout, 1)


def _render_value(value: Any, stdout: TextIO, depth: int = 0, key: str = "") -> None:
    indent = "  " * depth
    prefix = f"{indent}{key}: " if key else indent
    if isinstance(value, dict):
        if key:
            stdout.write(f"{indent}{key}:\n")
        for child_key, child_value in value.items():
            _render_value(child_value, stdout, depth + (1 if key else 0), str(child_key))
        return
    if isinstance(value, list):
        if key:
            stdout.write(f"{indent}{key}:\n")
        for item in value:
            if isinstance(item, (dict, list)):
                stdout.write(f"{indent}  -\n")
                _render_value(item, stdout, depth + 2)
            else:
                stdout.write(f"{indent}  - {item}\n")
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        stdout.write(f"{prefix}{value}\n")
        return
    stdout.write(f"{prefix}{json.dumps(value, ensure_ascii=False)}\n")


def _completion_candidates(text: str) -> list[str]:
    command, prefix = _completion_context(text)
    response = complete_cmd(prefix=prefix, command=command)
    data = response.get("data") or {}
    return [
        str(item.get("value") or item.get("label"))
        for item in data.get("completions", [])
        if item.get("value") or item.get("label")
    ]


def _completion_context(text: str) -> tuple[str, str]:
    stripped = text.lstrip()
    if not stripped:
        return "", ""
    parts = stripped.split()
    if len(parts) <= 1 and not stripped.endswith(" "):
        return "", parts[0]
    command = parts[0].lstrip("/")
    if stripped.endswith(" "):
        return command, ""
    return command, parts[-1]


def _completion_start_position(text_before_cursor: str) -> int:
    if not text_before_cursor or text_before_cursor.endswith(" "):
        return 0
    return -len(text_before_cursor.split()[-1])


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


def main() -> int:
    return run_terminal()


if __name__ == "__main__":
    raise SystemExit(main())
