"""ExtensionDraft — extracted message metadata + field candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from protocol_extend.schema import ExtensionSpec, missing_fields


@dataclass
class ExtensionDraft:
    afn: int | None = None
    di: str = ""
    description: str = ""
    dir: int | None = None
    add: bool | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    resp_fields: list[dict[str, Any]] = field(default_factory=list)
    pair: bool = False
    resp_description: str = ""
    section_id: str = ""
    candidate_id: str = ""
    title: str = ""
    extraction_report: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"  # pending | accepted | skipped | failed
    modify_history: list[dict[str, Any]] = field(default_factory=list)
    skip_reason: str = ""
    extension_file: str = ""
    last_error: str = ""
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    fidelity_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtensionDraft:
        return cls(
            afn=int(data["afn"]) if data.get("afn") is not None else None,
            di=str(data.get("di") or ""),
            description=str(data.get("description") or ""),
            dir=int(data["dir"]) if data.get("dir") is not None else None,
            add=data.get("add") if "add" in data else None,
            fields=list(data.get("fields") or []),
            resp_fields=list(data.get("resp_fields") or []),
            pair=bool(data.get("pair")),
            resp_description=str(data.get("resp_description") or ""),
            section_id=str(data.get("section_id") or ""),
            candidate_id=str(data.get("candidate_id") or ""),
            title=str(data.get("title") or ""),
            extraction_report=list(data.get("extraction_report") or []),
            status=str(data.get("status") or "pending"),
            modify_history=list(data.get("modify_history") or []),
            skip_reason=str(data.get("skip_reason") or ""),
            extension_file=str(data.get("extension_file") or ""),
            last_error=str(data.get("last_error") or ""),
            source_snapshot=dict(data.get("source_snapshot") or {}),
            fidelity_report=dict(data.get("fidelity_report") or {}),
        )

    def to_spec(self) -> ExtensionSpec:
        return ExtensionSpec(
            afn=self.afn,
            di=self.di,
            description=self.description,
            dir=self.dir,
            add=self.add,
            fields=list(self.fields),
            pair=self.pair,
            resp_description=self.resp_description,
            resp_fields=list(self.resp_fields),
        )

    @classmethod
    def from_spec(cls, spec: ExtensionSpec, **extra: Any) -> ExtensionDraft:
        return cls(
            afn=spec.afn,
            di=spec.di,
            description=spec.description,
            dir=spec.dir,
            add=spec.add,
            fields=list(spec.fields),
            resp_fields=list(spec.resp_fields),
            pair=spec.pair,
            resp_description=spec.resp_description,
            title=extra.get("title") or spec.description,
            section_id=str(extra.get("section_id") or ""),
            candidate_id=str(extra.get("candidate_id") or ""),
            extraction_report=list(extra.get("extraction_report") or []),
        )

    def update_from_spec(self, spec: ExtensionSpec) -> None:
        if spec.afn is not None:
            self.afn = spec.afn
        if spec.di:
            self.di = spec.di
        if spec.description:
            self.description = spec.description
        if spec.dir is not None:
            self.dir = spec.dir
        if spec.add is not None:
            self.add = spec.add
        if spec.fields:
            self.fields = list(spec.fields)
        if spec.resp_fields:
            self.resp_fields = list(spec.resp_fields)
        self.pair = spec.pair
        if spec.resp_description:
            self.resp_description = spec.resp_description

    def merge_user_input(self, user_input: dict[str, Any]) -> None:
        from protocol_extend.parser import merge_user_input

        spec = self.to_spec()
        merge_user_input(spec, user_input)
        self.update_from_spec(spec)

    def missing_fields(self) -> list[str]:
        return missing_fields(self.to_spec())

    def to_collection_entry(self) -> dict[str, Any]:
        from protocol_extend.source_snapshot import source_excerpt

        missing = self.missing_fields()
        field_summaries = [
            {"name": f.get("name", ""), "desc": f.get("desc", ""), "bytes": f.get("bytes")}
            for f in self.fields[:20]
        ]
        entry: dict[str, Any] = {
            "candidate_id": self.candidate_id or None,
            "section_id": self.section_id or None,
            "di": self.di or None,
            "afn": f"{self.afn:02X}" if self.afn is not None else None,
            "title": self.title or self.description,
            "description": self.description,
            "dir_hint": self.dir,
            "add_hint": self.add,
            "pair": self.pair,
            "fields_count": len(self.fields),
            "resp_fields_count": len(self.resp_fields),
            "field_summaries": field_summaries,
            "field_details": list(self.fields),
            "resp_field_details": list(self.resp_fields),
            "extraction_report": list(self.extraction_report),
            "missing": missing,
            "status": self.status,
            "ready": not missing,
        }
        if self.source_snapshot:
            entry["source_excerpt"] = source_excerpt(self.source_snapshot)
            entry["metadata_confidence"] = self.source_snapshot.get("metadata_confidence")
        return entry

    def merge_into_user_input(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.afn is not None:
            out["afn"] = f"{self.afn:02X}"
        if self.di:
            out["di"] = self.di
        if self.description:
            out["description"] = self.description
        if self.dir is not None:
            out["dir"] = "downlink" if self.dir == 0 else "uplink"
        if self.add is not None:
            out["add"] = self.add
        if self.fields:
            out["fields"] = self.fields
        if self.resp_fields:
            out["resp_fields"] = self.resp_fields
        if self.pair:
            out["pair"] = True
        if self.resp_description:
            out["resp_description"] = self.resp_description
        if self.section_id:
            out["section_id"] = self.section_id
        if self.candidate_id:
            out["candidate_id"] = self.candidate_id
        return out
