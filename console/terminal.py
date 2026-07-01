"""Plain terminal console for WireForge.

It stays in the normal terminal buffer, uses line input, and falls back cleanly
when prompt_toolkit is not installed.
"""

from __future__ import annotations

import argparse
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
    restore_state: Path | None = None,
) -> int:
    """Run the interactive plain terminal."""

    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    err = stderr or sys.stderr

    # 恢复会话状态（/split 继承）
    if restore_state:
        try:
            from console.session import restore_session
            summary = restore_session(restore_state)
            out.write(f"[restored state from {restore_state}]\n")
            vars_n = summary.get("variables_count", 0)
            rules_n = summary.get("rules_count", 0)
            if vars_n or rules_n:
                out.write(f"  variables: {vars_n}, rules: {rules_n}\n")
            errors = summary.get("errors", [])
            for e in errors:
                err.write(f"  restore warning: {e}\n")
        except Exception as e:
            err.write(f"restore failed: {e}\n")

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
    parser = argparse.ArgumentParser(
        prog="wireforge-terminal",
        description="WireForge interactive protocol console",
    )
    parser.add_argument(
        "--restore-state", type=Path, default=None,
        help="Restore session state from YAML file (used by /split)",
    )
    args = parser.parse_args(argv)
    return run_terminal(restore_state=args.restore_state)


if __name__ == "__main__":
    raise SystemExit(main())
