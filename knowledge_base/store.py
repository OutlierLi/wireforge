"""Small local RAG store for protocol documents.

The store is intentionally local and deterministic. It indexes protocol PDFs
and structured YAML/Markdown files into SQLite FTS5, then combines keyword
ranking with a tiny hashing vector so searches work without network services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DATABASE_ROOT = ROOT / "database"
INDEX_VERSION = 1
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
VECTOR_DIMS = 256
SUPPORTED_SUFFIXES = {".pdf", ".md", ".yaml", ".yml", ".json"}


@dataclass(slots=True)
class KnowledgeSource:
    source_id: str
    path: Path
    title: str
    tags: list[str]


def ingest(*, database_root: str | Path | None = None, rebuild: bool = False) -> dict[str, Any]:
    db_root = _database_root(database_root)
    index_root = db_root / "knowledge_index"
    index_root.mkdir(parents=True, exist_ok=True)
    conn = _connect(index_root / "chunks.sqlite")
    try:
        _init_db(conn)
        if rebuild:
            _clear_index(conn)
        sources = _discover_sources(db_root)
        source_count = 0
        chunk_count = 0
        for source in sources:
            chunk_count += _ingest_source(conn, source, db_root)
            source_count += 1
        conn.commit()
        (index_root / "index_meta.json").write_text(
            json.dumps(
                {"version": INDEX_VERSION, "sources": source_count, "chunks": chunk_count},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"sources": source_count, "chunks": chunk_count, "index": str(index_root / "chunks.sqlite")}
    finally:
        conn.close()


def search(query: str, *, database_root: str | Path | None = None, top_k: int = 5, tag: str | None = None) -> dict[str, Any]:
    db_root = _database_root(database_root)
    db_path = db_root / "knowledge_index" / "chunks.sqlite"
    if not db_path.exists():
        ingest(database_root=db_root, rebuild=True)
    conn = _connect(db_path)
    try:
        keyword_scores = _keyword_scores(conn, query, tag=tag, limit=max(top_k * 4, 20))
        substring_scores = _substring_scores(conn, query, tag=tag, limit=max(top_k * 4, 20))
        vector_scores = _vector_scores(conn, query, tag=tag, limit=max(top_k * 4, 20))
        scores: dict[int, float] = {}
        for chunk_id, score in keyword_scores.items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + score * 0.45
        for chunk_id, score in substring_scores.items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + score * 0.35
        for chunk_id, score in vector_scores.items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + score * 0.2
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return {"query": query, "results": [_chunk_record(conn, chunk_id, score) for chunk_id, score in ranked]}
    finally:
        conn.close()


def health(*, database_root: str | Path | None = None) -> dict[str, Any]:
    db_root = _database_root(database_root)
    db_path = db_root / "knowledge_index" / "chunks.sqlite"
    if not db_path.exists():
        return {"ok": False, "index": str(db_path), "sources": 0, "chunks": 0}
    conn = _connect(db_path)
    try:
        return {
            "ok": True,
            "index": str(db_path),
            "sources": int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
            "chunks": int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]),
        }
    finally:
        conn.close()


def list_sources(*, database_root: str | Path | None = None) -> dict[str, Any]:
    db_root = _database_root(database_root)
    db_path = db_root / "knowledge_index" / "chunks.sqlite"
    if not db_path.exists():
        return {"sources": []}
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT source_id, title, path, tags, chunk_count FROM sources ORDER BY source_id").fetchall()
        return {
            "sources": [
                {
                    "source_id": row["source_id"],
                    "title": row["title"],
                    "path": row["path"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "chunk_count": row["chunk_count"],
                }
                for row in rows
            ]
        }
    finally:
        conn.close()


def _database_root(path: str | Path | None = None) -> Path:
    return Path(path).resolve() if path else DATABASE_ROOT


def _discover_sources(db_root: Path) -> list[KnowledgeSource]:
    sources: list[KnowledgeSource] = []
    protocol_docs = db_root / "protocols"
    if protocol_docs.exists():
        for path in sorted(protocol_docs.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                sources.append(_source_from_path(path, db_root))
    yaml_root = ROOT / "protocol_tool" / "protocols"
    if yaml_root.exists():
        for path in sorted(yaml_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
                sources.append(_source_from_path(path, ROOT))
    return sources


def _source_from_path(path: Path, root: Path) -> KnowledgeSource:
    rel = path.relative_to(root)
    parts = rel.parts
    protocol = parts[1] if len(parts) > 2 and parts[0] in {"protocols", "protocol_tool"} else ""
    tags = [part for part in parts[:-1] if part not in {"database", "protocols", "protocol_tool"}]
    return KnowledgeSource(
        source_id=_source_id(rel),
        path=path,
        title=path.stem,
        tags=[tag for tag in tags if tag],
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            path TEXT NOT NULL,
            tags TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            heading TEXT,
            text TEXT NOT NULL,
            vector TEXT NOT NULL,
            FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            source_id UNINDEXED,
            content='chunks',
            content_rowid='id'
        );
        """
    )


def _clear_index(conn: sqlite3.Connection) -> None:
    conn.executescript("DELETE FROM chunks_fts; DELETE FROM chunks; DELETE FROM sources;")


def _ingest_source(conn: sqlite3.Connection, source: KnowledgeSource, db_root: Path) -> int:
    pages = _extract_pages(source.path)
    chunks = _chunk_pages(pages)
    conn.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source.source_id,))
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source.source_id,))
    conn.execute(
        """
        INSERT INTO sources(source_id, title, path, tags, chunk_count)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            title=excluded.title,
            path=excluded.path,
            tags=excluded.tags,
            chunk_count=excluded.chunk_count
        """,
        (source.source_id, source.title, _display_path(source.path), json.dumps(source.tags, ensure_ascii=False), len(chunks)),
    )
    for index, chunk in enumerate(chunks):
        cursor = conn.execute(
            """
            INSERT INTO chunks(source_id, chunk_index, page_start, page_end, heading, text, vector)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                index,
                chunk["page_start"],
                chunk["page_end"],
                chunk.get("heading"),
                chunk["text"],
                json.dumps(_embed(chunk["text"]), separators=(",", ":")),
            ),
        )
        conn.execute("INSERT INTO chunks_fts(rowid, text, source_id) VALUES (?, ?, ?)", (cursor.lastrowid, chunk["text"], source.source_id))
    return len(chunks)


def _extract_pages(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf_text(path)
        pages: list[dict[str, Any]] = []
        for index, page_text in enumerate(text.split("\f"), start=1):
            if page_text.strip():
                pages.append({"page": index, "text": _normalize_page_text(page_text)})
        return pages
    return [{"page": 1, "text": _normalize_page_text(path.read_text(encoding="utf-8-sig", errors="replace"))}]


def _extract_pdf_text(path: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        result = subprocess.run(
            [pdftotext, "-layout", str(path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout
    raise RuntimeError("pdftotext is required to index PDF protocol documents")


def _chunk_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in pages:
        text = str(page["text"]).strip()
        if not text:
            continue
        for section in _page_sections(text):
            chunks.extend(_split_text(section["text"], heading=section.get("heading"), page=int(page["page"])))
    return chunks


def _page_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    heading: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if lines:
            sections.append({"heading": heading, "text": "\n".join(lines)})
            lines = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line):
            flush()
            heading = line.lstrip("#").strip()
        lines.append(line)
    flush()
    return sections


def _split_text(text: str, *, heading: str | None, page: int) -> list[dict[str, Any]]:
    normalized = _normalize_text(text)
    if len(normalized) <= CHUNK_SIZE:
        return [{"text": normalized, "heading": heading, "page_start": page, "page_end": page}]
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_SIZE, len(normalized))
        if end < len(normalized):
            boundary = max(normalized.rfind("。", start, end), normalized.rfind("\n", start, end), normalized.rfind(".", start, end))
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1
        chunk_text = normalized[start:end].strip()
        if chunk_text:
            chunks.append({"text": chunk_text, "heading": heading, "page_start": page, "page_end": page})
        if end >= len(normalized):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _keyword_scores(conn: sqlite3.Connection, query: str, *, tag: str | None, limit: int) -> dict[int, float]:
    fts_query = _fts_query(query)
    if not fts_query:
        return {}
    rows = conn.execute(
        """
        SELECT chunks.id AS id, bm25(chunks_fts) AS rank, sources.tags AS tags
        FROM chunks_fts
        JOIN chunks ON chunks.id = chunks_fts.rowid
        JOIN sources ON sources.source_id = chunks.source_id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    scores: dict[int, float] = {}
    for row in rows:
        tags = json.loads(row["tags"] or "[]")
        if tag and tag not in tags:
            continue
        scores[int(row["id"])] = 1.0 / (1.0 + abs(float(row["rank"])))
    return scores


def _vector_scores(conn: sqlite3.Connection, query: str, *, tag: str | None, limit: int) -> dict[int, float]:
    query_vector = _embed(query)
    rows = conn.execute(
        """
        SELECT chunks.id, chunks.vector, sources.tags
        FROM chunks
        JOIN sources ON sources.source_id = chunks.source_id
        """
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for row in rows:
        tags = json.loads(row["tags"] or "[]")
        if tag and tag not in tags:
            continue
        scored.append((int(row["id"]), _cosine(query_vector, json.loads(row["vector"]))))
    return dict(sorted(scored, key=lambda item: item[1], reverse=True)[:limit])


def _substring_scores(conn: sqlite3.Connection, query: str, *, tag: str | None, limit: int) -> dict[int, float]:
    tokens = [token for token in _tokens(query) if len(token) >= 2]
    if not tokens:
        return {}
    rows = conn.execute(
        """
        SELECT chunks.id, chunks.text, sources.path, sources.tags
        FROM chunks
        JOIN sources ON sources.source_id = chunks.source_id
        """
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for row in rows:
        tags = json.loads(row["tags"] or "[]")
        if tag and tag not in tags:
            continue
        haystack = f"{row['path']}\n{row['text']}".lower()
        hits = 0
        for token in tokens:
            if token.lower() in haystack:
                hits += 1
        if hits:
            scored.append((int(row["id"]), hits / max(len(tokens), 1)))
    return dict(sorted(scored, key=lambda item: item[1], reverse=True)[:limit])


def _chunk_record(conn: sqlite3.Connection, chunk_id: int, score: float) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT chunks.*, sources.title, sources.path, sources.tags
        FROM chunks
        JOIN sources ON sources.source_id = chunks.source_id
        WHERE chunks.id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"chunk not found: {chunk_id}")
    return {
        "chunk_id": int(row["id"]),
        "source_id": row["source_id"],
        "title": row["title"],
        "path": row["path"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "heading": row["heading"],
        "score": round(float(score), 6),
        "tags": json.loads(row["tags"] or "[]"),
        "text": row["text"],
    }


def _embed(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMS
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 6) for item in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _tokens(text: str) -> list[str]:
    latin = re.findall(r"[A-Za-z0-9_]+", text.lower())
    cjk: list[str] = []
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        for size in range(2, 5):
            if len(segment) < size:
                continue
            cjk.extend(segment[index:index + size] for index in range(0, len(segment) - size + 1))
    return latin + cjk


def _fts_query(query: str) -> str:
    tokens = _tokens(query)
    return " OR ".join(_quote_fts(token) for token in tokens[:16])


def _quote_fts(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _normalize_page_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _is_heading(line: str) -> bool:
    return line.startswith("#") or bool(re.match(r"^第[一二三四五六七八九十0-9]+[章节条]", line))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _source_id(path: Path) -> str:
    clean = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", str(path.with_suffix(""))).strip("_")
    return clean[:160] or hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WireForge protocol knowledge base")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ingest_cmd = sub.add_parser("ingest")
    ingest_cmd.add_argument("--rebuild", action="store_true")
    ingest_cmd.add_argument("--database-root")
    search_cmd = sub.add_parser("search")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--top-k", type=int, default=5)
    search_cmd.add_argument("--tag")
    search_cmd.add_argument("--database-root")
    sub.add_parser("health")
    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        print(json.dumps(ingest(database_root=args.database_root, rebuild=args.rebuild), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "search":
        print(json.dumps(search(args.query, database_root=args.database_root, top_k=args.top_k, tag=args.tag), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "health":
        print(json.dumps(health(), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
