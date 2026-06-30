"""Tests for base protocol c_struct manifest generation."""

from __future__ import annotations

from pathlib import Path

import yaml

from protocol_extend.c_struct.manifest import VariantManifest, build_variant_dict
from protocol_extend.c_struct.parser import parse_c_struct

ROOT = Path(__file__).resolve().parent.parent
CSG = ROOT / "protocol_tool" / "protocols" / "csg_2016"
C_STRUCT = CSG / "c_struct"
MANIFEST = C_STRUCT / "manifest.yaml"
PAYLOADS_YAML = CSG / "variants" / "payloads"


def test_manifest_loads():
    manifest = VariantManifest.load(MANIFEST)
    assert len(manifest.variants) >= 57


def test_generated_payload_yaml_exists():
    files = list(PAYLOADS_YAML.glob("*.yaml"))
    assert len(files) >= 57


def test_empty_payload_variant_roundtrip():
    entry = next(
        e for e in VariantManifest.load(MANIFEST).variants
        if e.id == "csg_2016.afn03_query_vendor"
    )
    variant = build_variant_dict(entry, c_struct_root=C_STRUCT)
    assert variant["body"]["fields"] == []


def test_c_struct_roundtrip_query_slave_info_resp():
    entry = next(
        e for e in VariantManifest.load(MANIFEST).variants
        if e.id == "csg_2016.afn03_query_slave_info_resp"
    )
    variant = build_variant_dict(entry, c_struct_root=C_STRUCT)
    fields = variant["body"]["fields"]
    assert fields[2]["type"] == "array"
    assert fields[2]["count_ref"] == "response_slave_count"


def test_length_from_payload_roundtrip():
    entry = next(
        e for e in VariantManifest.load(MANIFEST).variants
        if e.id == "csg_2016.afn02_add_task"
    )
    source = (C_STRUCT / entry.c_struct).read_text(encoding="utf-8")
    defn = parse_c_struct(source)
    assert any(f.annotations.length_ref for f in defn.fields)
    variant = build_variant_dict(entry, c_struct_root=C_STRUCT)
    payload_fields = [f for f in variant["body"]["fields"] if f.get("length_from")]
    assert payload_fields


def test_afn_payloads_only_routing_groups():
    doc = yaml.safe_load((CSG / "variants" / "afn_payloads.yaml").read_text(encoding="utf-8"))
    for variant in doc["variants"]:
        fields = (variant.get("body") or {}).get("fields") or []
        if not fields:
            continue
        assert len(fields) == 1 and fields[0].get("type") == "routed_payload"
