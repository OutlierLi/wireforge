"""MCP stdio server entry for WireForge protocol-agent tasks."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp_servers.protocol.server import main


if __name__ == "__main__":
    raise SystemExit(main())
