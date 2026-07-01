"""Scan existing variants for DI/route conflicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from protocol_extend.dlt645_funcs import resolve_dlt645_func
from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent

_SELECTOR_FIELDS = ("di", "freeze_type", "event_type")


def _match_selector_value(match: dict[str, Any]) -> str | None:
    for key in _SELECTOR_FIELDS:
        val = match.get(key)
        if val:
            return str(val).upper().replace(" ", "")
    return None


def iter_variant_entries(variants_dir: Path | None = None) -> list[dict[str, Any]]:
    if variants_dir is None:
        return []
    entries: list[dict[str, Any]] = []
    if not variants_dir.exists():
        return entries
    for path in sorted(variants_dir.rglob("*.yaml")):
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
                if _match_selector_value(match):
                    entries.append({
                        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                        "id": var.get("id", ""),
                        "match": dict(match),
                    })
    return entries


def find_conflicts(spec: ExtensionSpec, variants_dir: Path | None = None) -> list[dict[str, Any]]:
    profile = spec.profile
    scan_dir = variants_dir or profile.variants_scan_dir(ROOT)
    keys_to_check = profile.conflict_keys(spec)
    selector_field = "di"
    if profile.id == "dlt645_2007":
        selector_field = resolve_dlt645_func(spec.func).selector_field

    conflicts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in iter_variant_entries(scan_dir):
        m = entry["match"]
        for want_di, want_dir, want_add in keys_to_check:
            if not profile.match_collides(
                m, want_di, want_dir, want_add, selector_field=selector_field,
            ):
                continue
            key = f"{entry['file']}:{entry['id']}"
            if key not in seen:
                seen.add(key)
                conflicts.append(entry)
    return conflicts
