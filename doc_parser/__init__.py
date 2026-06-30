"""DOCX → DocumentIR parsing for protocol extension."""

from doc_parser.document_ir import DocumentIR, MessageSection, ParagraphNode, TableNode
from doc_parser.parse_docx import parse_docx

__all__ = [
    "DocumentIR",
    "MessageSection",
    "ParagraphNode",
    "TableNode",
    "parse_docx",
]
