#!/usr/bin/env python3
"""Prepare WireForge protocol caches for MCP/Agent workflows."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_protocol.protocol_map import build_protocol_map_from_ir, compact_protocol_map
from protocol_tool.compiler.pipeline import compile_protocol
from protocol_tool.utils.graph import generate_svg

REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
COMPILED_DIR = ROOT / "compiled"
PROTOCOL_MAP_JSON = COMPILED_DIR / "protocol_map.json"
PROTOCOL_MAP_YAML = COMPILED_DIR / "protocol_map.yaml"

GENERATED_DIRS = [
    COMPILED_DIR,
    ROOT / "log",
    ROOT / "tests" / "check_output",
    ROOT / "tests" / "roundtrip_test" / "logs",
    ROOT / ".pytest_cache",
]


def main(argv: list[str] | None = None) -> int:
    args = set(argv if argv is not None else sys.argv[1:])
    clean = "--no-clean" not in args

    if clean:
        _clean_generated_outputs()

    protocols = _enabled_protocols()
    COMPILED_DIR.mkdir(parents=True, exist_ok=True)
    ir_by_protocol = {}
    for protocol in protocols:
        ir_by_protocol[protocol] = compile_protocol(str(REGISTRY), protocol, output_dir=str(COMPILED_DIR))

    protocol_map = compact_protocol_map(build_protocol_map_from_ir(COMPILED_DIR))
    PROTOCOL_MAP_JSON.write_text(
        json.dumps(protocol_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    PROTOCOL_MAP_YAML.write_text(_to_yaml(protocol_map), encoding="utf-8")
    for protocol, ir in ir_by_protocol.items():
        svg_path = COMPILED_DIR / f"{protocol}_routes.svg"
        generate_svg(ir, svg_path)
        print(f"generated {svg_path}")

    total = sum(len(proto.get("entries") or []) for proto in (protocol_map.get("protocols") or {}).values())
    print(f"prepared {len(protocols)} protocols")
    print(f"generated {PROTOCOL_MAP_JSON} ({total} entries)")
    print(f"generated {PROTOCOL_MAP_YAML}")
    return 0


def _clean_generated_outputs() -> None:
    for path in GENERATED_DIRS:
        if path.exists():
            shutil.rmtree(path)
            print(f"removed {path}")
    for pycache in ROOT.rglob("__pycache__"):
        if ".git" not in pycache.parts and pycache.exists():
            shutil.rmtree(pycache)
            print(f"removed {pycache}")


def _enabled_protocols() -> list[str]:
    text = REGISTRY.read_text(encoding="utf-8")
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to read protocol registry.yaml") from exc
    data = yaml.safe_load(text) or {}
    protocols: list[str] = []
    for item in data.get("protocols") or []:
        if item.get("enabled", True):
            protocols.append(str(item["id"]))
    return protocols


def _to_yaml(data: dict[str, Any]) -> str:
    lines = [f"version: {data.get('version', 1)}", "", "protocols:"]
    for proto, info in (data.get("protocols") or {}).items():
        lines.append(f"  {proto}:")
        lines.append(f'    name: "{info.get("name", proto)}"')
        lines.append("    entries:")
        for entry in info.get("entries") or []:
            path = ", ".join(entry.get("path") or [])
            fields = ", ".join(entry.get("fields") or [])
            route_params = json.dumps(entry.get("route_params") or {}, ensure_ascii=False, sort_keys=True)
            lines.append(f"      - id: {entry.get('id')}")
            lines.append(f"        entry_id: {entry.get('entry_id')}")
            lines.append(f"        leaf_id: {entry.get('leaf_id')}")
            lines.append(f'        name: "{entry.get("name", "")}"')
            lines.append(f'        description: "{entry.get("description", "")}"')
            lines.append(f"        path: [{path}]")
            lines.append(f"        route_params: {route_params}")
            if fields:
                lines.append(f"        fields: [{fields}]")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
