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

from agent_protocol.protocol_map import build_protocol_map_from_ir, compact_protocol_map, write_protocol_map_cache
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

    _generate_csg_variants_from_c_struct()

    protocols = _enabled_protocols()
    COMPILED_DIR.mkdir(parents=True, exist_ok=True)
    ir_by_protocol = {}
    for protocol in protocols:
        ir_by_protocol[protocol] = compile_protocol(str(REGISTRY), protocol, output_dir=str(COMPILED_DIR))

    protocol_map = compact_protocol_map(build_protocol_map_from_ir(COMPILED_DIR))
    json_path, yaml_path = write_protocol_map_cache(protocol_map, COMPILED_DIR)
    for protocol, ir in ir_by_protocol.items():
        svg_path = COMPILED_DIR / f"{protocol}_routes.svg"
        generate_svg(ir, svg_path)
        print(f"generated {svg_path}")

    total = sum(len(proto.get("entries") or []) for proto in (protocol_map.get("protocols") or {}).values())
    print(f"prepared {len(protocols)} protocols")
    print(f"generated {json_path} ({total} entries)")
    print(f"generated {yaml_path}")
    return 0


def _generate_csg_variants_from_c_struct() -> None:
    manifest = ROOT / "protocol_tool" / "protocols" / "csg_2016" / "c_struct" / "manifest.yaml"
    if not manifest.exists():
        return
    import importlib.util

    script = ROOT / "scripts" / "generate_csg_variants_from_c_struct.py"
    spec = importlib.util.spec_from_file_location("generate_csg_variants_from_c_struct", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(clean=False)


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


if __name__ == "__main__":
    raise SystemExit(main())
