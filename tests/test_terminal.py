from io import StringIO

from console.terminal import _completion_candidates, run_terminal


class _NonTtyStringIO(StringIO):
    def isatty(self):
        return False


def test_plain_terminal_executes_one_command_and_exits():
    stdin = _NonTtyStringIO("/help\n/exit\n")
    stdout = StringIO()
    stderr = StringIO()

    code = run_terminal(stdin=stdin, stdout=stdout, stderr=stderr)

    assert code == 0
    text = stdout.getvalue()
    assert "WireForge terminal" in text
    assert "success" in text
    assert "commands:" in text
    assert stderr.getvalue() == ""


def test_terminal_completion_uses_runtime_registry():
    candidates = _completion_candidates("/se")

    assert "/serial" in candidates
