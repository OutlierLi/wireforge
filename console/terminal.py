"""Plain terminal console for WireForge.

It stays in the normal terminal buffer, uses line input, and falls back cleanly
when prompt_toolkit is not installed.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
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
    from prompt_toolkit.patch_stdout import patch_stdout

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

    with patch_stdout(), _lab_event_subscription() as watcher:
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
            _execute_line(line, stdout, stderr, watcher)


def _run_plain_terminal(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    stdout.write("prompt_toolkit not available; using plain input mode.\n")
    with _lab_event_subscription(stdout) as watcher:
        while True:
            stdout.write("wireforge> ")
            stdout.flush()
            line = stdin.readline()
            if not line:
                return 0
            if _should_exit(line):
                return 0
            _execute_line(line, stdout, stderr, watcher)


def _execute_line(
    line: str,
    stdout: TextIO,
    stderr: TextIO,
    watcher: "_LabEventWatcher | None" = None,
) -> None:
    text = line.strip()
    if not text:
        return
    try:
        response = exec_text(text if text.startswith("/") else f"/{text}")
        if watcher:
            watcher.update_from_command(text, response)
        render_response(text, response, stdout)
    except KeyboardInterrupt:
        stdout.write("\n^C — interrupted\n")
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


@contextmanager
def _lab_event_subscription(stdout: TextIO | None = None):
    watcher = _LabEventWatcher(stdout)
    watcher.start()
    try:
        yield watcher
    finally:
        watcher.stop()


class _LabEventWatcher:
    def __init__(self, stdout: TextIO | None = None):
        self.stdout = stdout
        self._connections: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not _should_subscribe_labd_events():
            return
        self._thread = threading.Thread(target=self._run, name="wireforge-labd-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        try:
            from lab_service import get_lab_service

            lab = get_lab_service()
            seq = int(lab.event_cursor())
        except Exception:
            return

        while not self._stop.is_set():
            try:
                payload = lab.events_since(seq, limit=100, timeout_ms=1000)
                seq = int(payload.get("next_seq") or seq)
                for event in payload.get("events") or []:
                    if not self._is_interested(event):
                        continue
                    line = _format_lab_event(event)
                    if line:
                        self._write(line)
            except Exception:
                self._stop.wait(1.0)

    def _write(self, line: str) -> None:
        if self.stdout is None:
            print(line, flush=True)
            return
        self.stdout.write(line + "\n")
        self.stdout.flush()

    def update_from_command(self, text: str, response: dict[str, Any]) -> None:
        if response.get("status") != "success":
            return
        if not _is_serial_command(text):
            return
        sub = _serial_subcommand(text)
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        name = _response_connection_name(data)
        if not name:
            return
        if sub == "disconnect":
            self.unsubscribe(name)
        elif sub in {"connect", "open", "send"}:
            self.subscribe(name)

    def subscribe(self, name: str) -> None:
        if not name:
            return
        with self._lock:
            self._connections.add(name)

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._connections.discard(name)

    def _is_interested(self, event: dict[str, Any]) -> bool:
        connection = str(event.get("connection") or "")
        if not connection:
            return False
        with self._lock:
            return connection in self._connections


def _should_subscribe_labd_events() -> bool:
    try:
        from lab_service.service import _rpc_enabled

        return _rpc_enabled()
    except Exception:
        return False


def _format_lab_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    direction = {
        "serial_tx": "TX",
        "serial_rx": "RX",
        "serial_tx_failed": "TX failed",
    }.get(event_type)
    if not direction:
        return ""
    connection = str(event.get("connection") or "?")
    hex_text = str(event.get("hex") or "")
    detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
    error = str(detail.get("error") or "")
    suffix = f" ({error})" if error else ""
    return f"[labd][{connection}] {direction}: {hex_text}{suffix}"


def _is_serial_command(text: str) -> bool:
    stripped = text.strip()
    return stripped == "/serial" or stripped.startswith("/serial ") or stripped == "serial" or stripped.startswith("serial ")


def _serial_subcommand(text: str) -> str:
    parts = text.strip().split()
    if not parts:
        return ""
    if parts[0] in {"/serial", "serial"} and len(parts) > 1:
        return parts[1].strip()
    return ""


def _response_connection_name(data: dict[str, Any]) -> str:
    for key in ("to", "name", "id"):
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _should_exit(line: str) -> bool:
    return line.strip() in {"/exit", "/quit", "exit", "quit"}


def main(argv: list[str] | None = None) -> int:
    return run_terminal()


if __name__ == "__main__":
    raise SystemExit(main())
