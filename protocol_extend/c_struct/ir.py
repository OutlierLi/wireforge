"""Intermediate representation for parsed C struct definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CStructMetadata:
    afn: int | None = None
    di: str = ""
    dir: int | None = None
    add: bool | None = None
    description: str = ""
    pair: bool = False
    resp_description: str = ""


@dataclass
class CFieldAnnotations:
    desc: str = ""
    enum_values: dict[str, str] = field(default_factory=dict)
    domain: str = ""
    alias: str = ""
    unit: str = ""
    scale: float | None = None
    count_ref: str = ""
    length_ref: str = ""
    item_name: str = ""
    hex_type: bool = False
    default: str = ""
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class CFieldDef:
    name: str
    c_type: str
    array_size: int | None = None
    is_flexible_array: bool = False
    annotations: CFieldAnnotations = field(default_factory=CFieldAnnotations)
    subfields: list[CFieldDef] = field(default_factory=list)
    offset: int = 0
    wire_size: int | None = None
    line: int = 0

    @property
    def is_struct(self) -> bool:
        return bool(self.subfields)

    @property
    def is_array(self) -> bool:
        return self.array_size is not None or self.is_flexible_array


@dataclass
class CStructDef:
    name: str = ""
    metadata: CStructMetadata = field(default_factory=CStructMetadata)
    fields: list[CFieldDef] = field(default_factory=list)
    source_path: str | None = None
    packed: bool = True

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "field_count": len(self.fields),
            "metadata": {
                "afn": f"{self.metadata.afn:02X}" if self.metadata.afn is not None else None,
                "di": self.metadata.di or None,
                "dir": self.metadata.dir,
                "description": self.metadata.description or None,
            },
            "fields": [
                {
                    "name": f.name,
                    "c_type": f.c_type,
                    "offset": f.offset,
                    "wire_size": f.wire_size,
                    "line": f.line,
                }
                for f in self.fields
            ],
        }
