"""命令树 schema 测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from console.api import exec_cmd, complete_cmd
from console.command import registry
from console.command_schema import effective_params, validate_args, sorted_params


@pytest.fixture(autouse=True)
def _close_serial_after():
    yield
    import wireforge_serial.api as serial_api
    for name in list(serial_api._connections.keys()):
        exec_cmd("serial", {"sub": "close", "to": name})


def _ok(r, msg=""):
    assert r["status"] == "success", f"{msg} | {r}"


def _need_input(r, key: str):
    assert r["status"] == "need_input", r
    keys = [f["key"] for f in r.get("input_schema", [])]
    assert key in keys, keys


def _param_names(help_params: list) -> list[str]:
    return [p["name"] for p in help_params]


class TestAllCommandsTree:
    def test_all_commands_have_sub_commands(self):
        for name in registry.names():
            cmd = registry.get(name)
            assert cmd is not None
            assert cmd.sub_commands, f"/{name} missing sub_commands"
            assert cmd.params == {}, f"/{name} should have empty top-level params"

    def test_help_decode_sub(self):
        r = exec_cmd("help", {"target": "/decode decode"})
        _ok(r)
        names = _param_names(r["data"]["params"])
        assert names.index("--proto") < names.index("--hex")

    def test_validate_decode_missing_hex(self):
        r = exec_cmd("decode", {"proto": "csg"})
        _need_input(r, "hex")

    def test_validate_var_import_missing_file(self):
        r = exec_cmd("var", {"sub": "import"})
        _need_input(r, "file")

    def test_validate_run_missing_file(self):
        r = exec_cmd("run", {"sub": "execute"})
        _need_input(r, "file")

    def test_help_connect_param_order(self):
        cmd = registry.get("serial")
        params = effective_params(cmd, "connect")
        keys = [k for k, _ in sorted_params(params)]
        assert keys.index("port") < keys.index("baudrate")


class TestSerialSchema:
    def test_help_top_level_shows_subs_not_flat_params(self):
        r = exec_cmd("help", {"target": "/serial"})
        _ok(r)
        assert r["data"]["command"] == "/serial"
        assert any(s["name"] == "/serial connect" for s in r["data"]["sub_commands"])
        assert not any(p["name"] == "--port" for p in r["data"]["params"])

    def test_help_connect_shows_required_port(self):
        r = exec_cmd("help", {"target": "/serial connect"})
        _ok(r)
        port = next(p for p in r["data"]["params"] if p["name"] == "--port")
        assert port["required"] is True
        name = next(p for p in r["data"]["params"] if p["name"] == "--to")
        assert name.get("recommended") is True
        assert "--hex" not in {p["name"] for p in r["data"]["params"]}

    def test_help_send_shows_build_and_hex(self):
        r = exec_cmd("help", {"target": "/serial send"})
        _ok(r)
        names = {p["name"] for p in r["data"]["params"]}
        assert "--build" in names
        assert "--hex" in names
        hex_p = next(p for p in r["data"]["params"] if p["name"] == "--hex")
        assert hex_p["required"] is False
        assert "--port" not in names

    def test_validate_connect_missing_port(self):
        r = exec_cmd("serial", {"sub": "connect", "to": "x"})
        _need_input(r, "port")

    def test_validate_send_missing_hex(self):
        exec_cmd("serial", {"sub": "connect", "port": "mock://loop", "to": "s"})
        r = exec_cmd("serial", {"sub": "send", "to": "s"})
        _need_input(r, "hex")

    def test_complete_serial_subcommands(self):
        r = complete_cmd(command="serial", prefix="")
        subs = [c["value"] for c in r["data"]["completions"] if c["kind"] == "sub_command"]
        assert "connect" in subs
        assert "send" in subs

    def test_complete_serial_connect_params(self):
        r = complete_cmd(command="serial", sub="connect", prefix="")
        keys = [c["value"] for c in r["data"]["completions"]]
        assert "--port" in keys
        assert "--hex" not in keys

    def test_effective_params_per_sub(self):
        cmd = registry.get("serial")
        assert cmd is not None
        connect = effective_params(cmd, "connect")
        send = effective_params(cmd, "send")
        assert connect["port"]["required"] is True
        assert "port" not in send
        assert "hex" in send
        assert "build" in send
        assert send["hex"]["required"] is False

    def test_validate_args_direct(self):
        cmd = registry.get("serial")
        err = validate_args(cmd, {"sub": "connect", "name": "a"})
        assert err is not None
        assert err["detail"]["missing"][0]["key"] == "port"
