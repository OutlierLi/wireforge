#!/usr/bin/env python3
"""Generate the deterministic protocol map from compiled IR files."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_protocol.protocol_map import build_protocol_map_from_ir, compact_protocol_map


def to_yaml(data: dict) -> str:
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


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    output = Path(args[0]) if args else ROOT / "compiled" / "protocol_map.json"
    data = compact_protocol_map(build_protocol_map_from_ir())
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".yaml", ".yml"}:
        output.write_text(to_yaml(data), encoding="utf-8")
    else:
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(proto.get("entries") or []) for proto in (data.get("protocols") or {}).values())
    print(f"generated {output} ({total} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
