"""Manifest-driven variant generation from C struct sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from protocol_extend.c_struct.parser import parse_c_struct, read_c_struct_file
from protocol_extend.c_struct.to_yaml import c_struct_to_yaml_fields
from protocol_extend.c_struct.validator import validate_c_struct


@dataclass
class VariantManifestEntry:
    id: str
    router: str
    match: dict[str, Any]
    description: str = ""
    c_struct: str = ""
    source: str = "c_struct"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariantManifestEntry:
        return cls(
            id=str(data["id"]),
            router=str(data["router"]),
            match=dict(data.get("match") or {}),
            description=str(data.get("description") or ""),
            c_struct=str(data.get("c_struct") or ""),
            source=str(data.get("source") or "c_struct"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "router": self.router,
            "match": self.match,
            "source": self.source,
        }
        if self.description:
            out["description"] = self.description
        if self.c_struct:
            out["c_struct"] = self.c_struct
        return out


@dataclass
class VariantManifest:
    variants: list[VariantManifestEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> VariantManifest:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = [VariantManifestEntry.from_dict(item) for item in data.get("variants") or []]
        return cls(variants=entries)

    def save(self, path: Path) -> None:
        doc = {"variants": [entry.to_dict() for entry in self.variants]}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def build_variant_dict(
    entry: VariantManifestEntry,
    *,
    c_struct_root: Path,
    desc_key: str = "description",
) -> dict[str, Any]:
    if not entry.c_struct:
        raise ValueError(f"manifest entry {entry.id} missing c_struct path")

    source_path = c_struct_root / entry.c_struct
    source, _ = read_c_struct_file(source_path)
    defn = parse_c_struct(source, path=str(source_path))
    validate_c_struct(defn)
    fields = c_struct_to_yaml_fields(defn, desc_key=desc_key)

    variant: dict[str, Any] = {
        "kind": "variant",
        "id": entry.id,
        "router": entry.router,
        "match": dict(entry.match),
        "body": {"type": "struct", "fields": fields},
    }
    if entry.description:
        variant["description"] = entry.description
    return variant


def render_variant_yaml(
    entry: VariantManifestEntry,
    *,
    c_struct_root: Path,
    desc_key: str = "description",
) -> str:
    variant = build_variant_dict(entry, c_struct_root=c_struct_root, desc_key=desc_key)
    header = (
        f"# Generated from {entry.c_struct}\n"
        f"# Source: c_struct manifest — do not edit by hand\n\n"
    )
    body = yaml.dump({"variants": [variant]}, allow_unicode=True, sort_keys=False)
    return header + body
