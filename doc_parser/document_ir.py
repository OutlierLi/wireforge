"""DocumentIR — structured representation of parsed DOCX content."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParagraphNode:
    id: str
    index: int
    style: str | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParagraphNode:
        return cls(
            id=str(data["id"]),
            index=int(data["index"]),
            style=data.get("style"),
            text=str(data.get("text") or ""),
        )


@dataclass
class TableNode:
    id: str
    index: int
    title: str | None
    headers: list[str]
    rows: list[list[str]]
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableNode:
        return cls(
            id=str(data["id"]),
            index=int(data["index"]),
            title=data.get("title"),
            headers=[str(h) for h in data.get("headers") or []],
            rows=[[str(c) for c in row] for row in data.get("rows") or []],
            provenance=dict(data.get("provenance") or {}),
        )


@dataclass
class MessageSection:
    section_id: str
    title: str
    afn: int | None = None
    di: str | None = None
    description: str = ""
    paragraph_ids: list[str] = field(default_factory=list)
    table_ids: list[str] = field(default_factory=list)
    dir_hint: int | None = None
    add_hint: bool | None = None
    metadata_confidence: str = "low"
    metadata_sources: list[str] = field(default_factory=list)
    missing_metadata: list[str] = field(default_factory=list)

    def ready_to_extend(self) -> bool:
        return bool(self.di)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageSection:
        return cls(
            section_id=str(data["section_id"]),
            title=str(data.get("title") or ""),
            afn=int(data["afn"]) if data.get("afn") is not None else None,
            di=str(data["di"]) if data.get("di") else None,
            description=str(data.get("description") or ""),
            paragraph_ids=list(data.get("paragraph_ids") or []),
            table_ids=list(data.get("table_ids") or []),
            dir_hint=int(data["dir_hint"]) if data.get("dir_hint") is not None else None,
            add_hint=data.get("add_hint") if "add_hint" in data else None,
            metadata_confidence=str(data.get("metadata_confidence") or "low"),
            metadata_sources=list(data.get("metadata_sources") or []),
            missing_metadata=list(data.get("missing_metadata") or []),
        )


@dataclass
class DocumentIR:
    doc_id: str
    source_path: str
    paragraphs: list[ParagraphNode] = field(default_factory=list)
    tables: list[TableNode] = field(default_factory=list)
    sections: list[MessageSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "tables": [t.to_dict() for t in self.tables],
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentIR:
        return cls(
            doc_id=str(data.get("doc_id") or ""),
            source_path=str(data.get("source_path") or ""),
            paragraphs=[ParagraphNode.from_dict(p) for p in data.get("paragraphs") or []],
            tables=[TableNode.from_dict(t) for t in data.get("tables") or []],
            sections=[MessageSection.from_dict(s) for s in data.get("sections") or []],
        )

    def summary(self) -> dict[str, int]:
        return {
            "paragraphs": len(self.paragraphs),
            "tables": len(self.tables),
            "sections": len(self.sections),
        }

    def paragraph_by_id(self, pid: str) -> ParagraphNode | None:
        for p in self.paragraphs:
            if p.id == pid:
                return p
        return None

    def table_by_id(self, tid: str) -> TableNode | None:
        for t in self.tables:
            if t.id == tid:
                return t
        return None

    def section_by_id(self, section_id: str) -> MessageSection | None:
        for s in self.sections:
            if s.section_id == section_id:
                return s
        return None
