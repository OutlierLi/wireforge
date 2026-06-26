import json
from pathlib import Path


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
