#!/usr/bin/env python3
"""One-time migration: afn_payloads.yaml DI bodies → c_struct sources + manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from protocol_extend.c_struct.from_yaml import render_c_struct_source, slug_from_variant_id, struct_name_from_variant_id
from protocol_extend.c_struct.manifest import VariantManifest, VariantManifestEntry

ROOT = Path(__file__).resolve().parent.parent
CSG_ROOT = ROOT / "protocol_tool" / "protocols" / "csg_2016"
AFN_PAYLOADS = CSG_ROOT / "variants" / "afn_payloads.yaml"
C_STRUCT_ROOT = CSG_ROOT / "c_struct"
PAYLOADS_DIR = C_STRUCT_ROOT / "payloads"
MANIFEST_PATH = C_STRUCT_ROOT / "manifest.yaml"


def _is_group_variant(variant: dict) -> bool:
    fields = (variant.get("body") or {}).get("fields") or []
    return len(fields) == 1 and fields[0].get("type") == "routed_payload"


def _is_empty_variant(variant: dict) -> bool:
    fields = (variant.get("body") or {}).get("fields") or []
    return not fields


def _should_migrate(variant: dict) -> bool:
    return not _is_group_variant(variant)


def _migrate_variant(variant: dict, manifest: VariantManifest, *, dry_run: bool) -> None:
    variant_id = str(variant["id"])
    slug = slug_from_variant_id(variant_id)
    rel_h = f"payloads/{slug}.h"
    struct_name = struct_name_from_variant_id(variant_id)
    fields = (variant.get("body") or {}).get("fields") or []
    metadata = {
        "desc": variant.get("description") or variant_id,
    }
    if variant.get("match", {}).get("di"):
        metadata["di"] = variant["match"]["di"]

    source = render_c_struct_source(
        struct_name=struct_name,
        fields=fields,
        metadata=metadata,
    )
    entry = VariantManifestEntry(
        id=variant_id,
        router=str(variant["router"]),
        match=dict(variant.get("match") or {}),
        description=str(variant.get("description") or ""),
        c_struct=rel_h,
    )
    manifest.variants.append(entry)

    if dry_run:
        print(f"would write {rel_h} ({len(fields)} fields)")
        return

    PAYLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (C_STRUCT_ROOT / rel_h).write_text(source, encoding="utf-8")


def migrate(*, dry_run: bool = False) -> None:
    doc = yaml.safe_load(AFN_PAYLOADS.read_text(encoding="utf-8")) or {}
    variants = list(doc.get("variants") or [])

    kept: list[dict] = []
    manifest = VariantManifest()

    for variant in variants:
        if not _should_migrate(variant):
            kept.append(variant)
            continue
        _migrate_variant(variant, manifest, dry_run=dry_run)

    if dry_run:
        print(f"would keep {len(kept)} routing variants in afn_payloads.yaml")
        print(f"would migrate {len(manifest.variants)} payload variants")
        return

    doc["variants"] = kept
    header = (
        "# CSG 2016 routing groups only\n"
        "# DI payload fields live in c_struct/ and variants/payloads/ (generated)\n\n"
    )
    body = yaml.dump({k: v for k, v in doc.items()}, allow_unicode=True, sort_keys=False)
    AFN_PAYLOADS.write_text(header + body, encoding="utf-8")
    manifest.save(MANIFEST_PATH)
    print(f"migrated {len(manifest.variants)} variants → {C_STRUCT_ROOT}")
    print(f"kept {len(kept)} variants in {AFN_PAYLOADS}")


def migrate_empty_only(*, dry_run: bool = False) -> None:
    """Append zero-byte payload variants from afn_payloads into existing manifest."""
    doc = yaml.safe_load(AFN_PAYLOADS.read_text(encoding="utf-8")) or {}
    variants = list(doc.get("variants") or [])
    manifest = VariantManifest.load(MANIFEST_PATH) if MANIFEST_PATH.exists() else VariantManifest()
    existing_ids = {entry.id for entry in manifest.variants}

    kept: list[dict] = []
    added = 0
    for variant in variants:
        if not _is_empty_variant(variant) or _is_group_variant(variant):
            kept.append(variant)
            continue
        if str(variant["id"]) in existing_ids:
            kept.append(variant)
            continue
        _migrate_variant(variant, manifest, dry_run=dry_run)
        added += 1

    if dry_run:
        print(f"would migrate {added} empty payload variants")
        print(f"would keep {len(kept)} variants in afn_payloads.yaml")
        return

    doc["variants"] = kept
    header = (
        "# CSG 2016 routing groups only\n"
        "# DI payload fields live in c_struct/ and variants/payloads/ (generated)\n\n"
    )
    body = yaml.dump({k: v for k, v in doc.items()}, allow_unicode=True, sort_keys=False)
    AFN_PAYLOADS.write_text(header + body, encoding="utf-8")
    manifest.save(MANIFEST_PATH)
    print(f"added {added} empty payload variants → {C_STRUCT_ROOT}")
    print(f"kept {len(kept)} variants in {AFN_PAYLOADS}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--empty-only",
        action="store_true",
        help="migrate only zero-byte payloads into existing manifest",
    )
    args = parser.parse_args()
    if args.empty_only:
        migrate_empty_only(dry_run=args.dry_run)
    else:
        migrate(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
