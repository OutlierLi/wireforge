#!/usr/bin/env python3
"""Generate CSG variant YAML from c_struct manifest (base protocol payloads)."""

from __future__ import annotations

import argparse
from pathlib import Path

from protocol_extend.c_struct.manifest import VariantManifest, render_variant_yaml

ROOT = Path(__file__).resolve().parent.parent
CSG_ROOT = ROOT / "protocol_tool" / "protocols" / "csg_2016"
C_STRUCT_ROOT = CSG_ROOT / "c_struct"
MANIFEST_PATH = C_STRUCT_ROOT / "manifest.yaml"
OUTPUT_DIR = CSG_ROOT / "variants" / "payloads"


def generate(*, clean: bool = False) -> int:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"manifest not found: {MANIFEST_PATH}")

    manifest = VariantManifest.load(MANIFEST_PATH)
    if clean and OUTPUT_DIR.exists():
        for path in OUTPUT_DIR.glob("*.yaml"):
            path.unlink()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry in manifest.variants:
        slug = entry.id.rsplit(".", 1)[-1]
        out_path = OUTPUT_DIR / f"{slug}.yaml"
        out_path.write_text(
            render_variant_yaml(entry, c_struct_root=C_STRUCT_ROOT),
            encoding="utf-8",
        )
        count += 1
    print(f"generated {count} variant file(s) → {OUTPUT_DIR}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="Remove existing generated yaml first")
    args = parser.parse_args()
    generate(clean=args.clean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
