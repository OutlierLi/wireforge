"""Scan existing variants for DI/route conflicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent
CSG_VARIANTS_DIR = ROOT / "protocol_tool" / "protocols" / "csg_2016" / "variants"


def iter_variant_entries(variants_dir: Path | None = None) -> list[dict[str, Any]]:
    base = variants_dir or CSG_VARIANTS_DIR
    entries: list[dict[str, Any]] = []
    if not base.exists():
        return entries
    for path in sorted(base.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data:
            continue
        variants = data.get("variants", [data] if isinstance(data, dict) and data.get("kind") == "variant" else [])
        if not isinstance(variants, list):
            continue
        for var in variants:
            if isinstance(var, dict) and var.get("kind", "variant") == "variant":
                match = var.get("match") or {}
                if match.get("di"):
                    entries.append({
                        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                        "id": var.get("id", ""),
                        "match": dict(match),
                    })
    return entries


def find_conflicts(spec: ExtensionSpec, variants_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return existing variants that collide on di+dir+add."""
    keys_to_check: list[tuple[str, int | None, int | None]] = []
    if spec.pair:
        if spec.afn == 0:
            keys_to_check.append((spec.di, None, spec.add))
            keys_to_check.append((spec.di, None, spec.add))
        else:
            keys_to_check.append((spec.di, 0, spec.add))
            keys_to_check.append((spec.di, 1, spec.add))
    else:
        d = spec.dir if spec.afn_uses_dir() else None
        keys_to_check.append((spec.di, d, spec.add))

    conflicts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in iter_variant_entries(variants_dir):
        m = entry["match"]
        for want_di, want_dir, want_add in keys_to_check:
            if not _match_collides(m, want_di, want_dir, want_add):
                continue
            key = f"{entry['file']}:{entry['id']}"
            if key not in seen:
                seen.add(key)
                conflicts.append(entry)
    return conflicts


def _match_collides(
    match: dict[str, Any],
    want_di: str,
    want_dir: int | None,
    want_add: int | None,
) -> bool:
    di = str(match.get("di", "")).upper().replace(" ", "")
    if di != want_di:
        return False
    entry_add = match.get("control.add")
    if want_add is not None and entry_add is not None and int(entry_add) != want_add:
        return False
    entry_dir = match.get("control.dir")
    if want_dir is not None:
        if entry_dir is None:
            return False
        if int(entry_dir) != want_dir:
            return False
    return True
