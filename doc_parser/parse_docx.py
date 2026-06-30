"""Parse .docx files into DocumentIR."""

from __future__ import annotations

import hashlib
from pathlib import Path

from doc_parser.document_ir import DocumentIR, ParagraphNode, TableNode
from doc_parser.metadata_extractor import extract_afn_di_from_text  # noqa: F401 — re-export
from doc_parser.normalize_table import parse_table_structure


def _require_docx():
    try:
        from docx import Document
        return Document
    except ImportError as exc:
        raise ImportError(
            "python-docx is required for DOCX parsing. "
            "Install with: pip install python-docx"
        ) from exc


def resolve_docx_path(path: str | Path, *, root: Path | None = None) -> Path:
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p.resolve()
    base = root or Path(__file__).resolve().parent.parent
    candidate = (base / p).resolve()
    if candidate.exists():
        return candidate
    if p.exists():
        return p.resolve()
    raise FileNotFoundError(f"DOCX not found: {path}")


def parse_docx(path: str | Path, *, root: Path | None = None) -> DocumentIR:
    Document = _require_docx()
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    resolved = resolve_docx_path(path, root=root)
    if resolved.suffix.lower() != ".docx":
        raise ValueError(f"unsupported document format (docx only): {resolved.suffix}")

    doc = Document(str(resolved))
    doc_id = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]

    paragraphs: list[ParagraphNode] = []
    tables: list[TableNode] = []
    last_para_id: str | None = None
    table_ti = 0

    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            para = Paragraph(block, doc)
            text = para.text.strip()
            if not text:
                continue
            i = len(paragraphs)
            pid = f"p{i}"
            style_name = para.style.name if para.style else None
            paragraphs.append(ParagraphNode(id=pid, index=i, style=style_name, text=text))
            last_para_id = pid
        elif tag == "tbl":
            table = Table(block, doc)
            raw_rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            structured = parse_table_structure(raw_rows)
            title = None
            if last_para_id:
                prev = next((p for p in paragraphs if p.id == last_para_id), None)
                if prev:
                    title = prev.text
            tables.append(TableNode(
                id=f"t{table_ti}",
                index=table_ti,
                title=title,
                headers=structured["headers"],
                rows=structured["rows"],
                provenance={
                    "source_path": str(resolved),
                    "table_index": table_ti,
                    "paragraph_before": last_para_id,
                },
            ))
            table_ti += 1

    if not paragraphs and not tables:
        raise ValueError(f"empty document: {resolved}")

    return DocumentIR(
        doc_id=doc_id,
        source_path=str(resolved),
        paragraphs=paragraphs,
        tables=tables,
        sections=[],
    )


from doc_parser.metadata_extractor import extract_afn_di_from_text
