import json
import subprocess
import sys
from pathlib import Path

INIT_REQUEST = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1.0"},
    },
}) + "\n"

MCP_ENTRY_SCRIPTS = [
    "scripts/python/wireforge_mcp_server.py",
    "scripts/python/wireforge_test_mcp_server.py",
    "scripts/python/wireforge_extend_mcp_server.py",
    "scripts/python/wireforge_exec_test_mcp_server.py",
]


def test_opencode_config_registers_wireforge_mcp():
    root = Path(__file__).resolve().parent.parent
    config_path = root / ".opencode" / "opencode.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["instructions"] == ["../AGENTS.md"]
    assert (config_path.parent / config["instructions"][0]).resolve() == root / "AGENTS.md"

    mcp = config["mcp"]["wireforge"]
    assert mcp["enabled"] is True
    assert mcp["type"] == "local"
    assert mcp["command"] == ["python3", "scripts/python/wireforge_mcp_server.py"]
    assert (root / mcp["command"][1]).exists()


def test_opencode_config_registers_wireforge_test_mcp():
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / ".opencode" / "opencode.json").read_text(encoding="utf-8"))

    mcp = config["mcp"]["wireforge-test"]
    assert mcp["enabled"] is True
    assert mcp["type"] == "local"
    assert mcp["command"] == ["python3", "scripts/python/wireforge_test_mcp_server.py"]
    assert (root / mcp["command"][1]).exists()


def test_opencode_config_registers_wireforge_exec_test_mcp():
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / ".opencode" / "opencode.json").read_text(encoding="utf-8"))

    mcp = config["mcp"]["wireforge-exec-test"]
    assert mcp["enabled"] is True
    assert mcp["type"] == "local"
    assert mcp["command"] == ["python3", "scripts/python/wireforge_exec_test_mcp_server.py"]
    assert (root / mcp["command"][1]).exists()


def test_opencode_mcp_entry_scripts_respond_to_initialize():
    root = Path(__file__).resolve().parent.parent
    for script in MCP_ENTRY_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, script],
            input=INIT_REQUEST,
            text=True,
            capture_output=True,
            cwd=root,
            timeout=10,
            check=False,
        )
        assert proc.returncode == 0, (
            f"{script} exited {proc.returncode}: {proc.stderr.strip()}"
        )
        line = proc.stdout.strip().splitlines()[0]
        payload = json.loads(line)
        assert payload.get("id") == 1
        assert "result" in payload, f"{script} missing result: {payload}"
        server_name = payload["result"]["serverInfo"]["name"]
        assert server_name, f"{script} empty serverInfo.name"
