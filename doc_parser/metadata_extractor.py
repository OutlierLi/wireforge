"""Extract AFN/DI/dir/add hints from text and key-value table rows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_AFN_PATTERNS = (
    re.compile(r"AFN\s*[=:]?\s*0*([0-9A-Fa-f]{1,2})\b", re.I),
    re.compile(r"应用功能码\s*AFN?\s*0*([0-9A-Fa-f]{1,2})\b", re.I),
    re.compile(r"功能码\s*[:：]?\s*0*([0-9A-Fa-f]{1,2})\b", re.I),
)

_DI_PATTERNS = (
    re.compile(r"DI\s*[=:\s]*([0-9A-Fa-f]{8})\b", re.I),
    re.compile(r"数据标识\s*[:：]?\s*([0-9A-Fa-f]{8})\b", re.I),
    re.compile(r"\b(E[0-9A-Fa-f]{7})\b", re.I),
)

_SPACED_DI = re.compile(r"E8(?:\s+[0-9A-Fa-f]{2}){3}", re.I)
_HEX_BYTE = re.compile(r"^[0-9A-Fa-f]{2}$")
_DI_COL_KEYS = ("di3", "di2", "di1", "di0", "di")
_TITLE_COL_KEYS = ("名称", "说明", "描述", "功能")
_DIR_COL_KEYS = ("方向", "传输方向", "dir")

_KV_AFN_KEYS = ("afn", "功能码", "应用功能码", "应用层功能码")
_KV_DI_KEYS = ("di", "数据标识", "数据标识码", "标识符")
_KV_DIR_KEYS = ("方向", "dir", "传输方向")
_KV_ADD_KEYS = ("地址", "add", "地址域", "带地址")


@dataclass
class MetadataHints:
    afn: int | None = None
    di: str | None = None
    dir_hint: int | None = None
    add_hint: bool | None = None
    confidence: str = "low"
    sources: list[str] = field(default_factory=list)

    def merge(self, other: MetadataHints) -> None:
        if other.afn is not None and self.afn is None:
            self.afn = other.afn
            self.sources.extend(other.sources)
        if other.di and not self.di:
            self.di = other.di.upper()
            self.sources.extend(other.sources)
        if other.dir_hint is not None and self.dir_hint is None:
            self.dir_hint = other.dir_hint
        if other.add_hint is not None and self.add_hint is None:
            self.add_hint = other.add_hint
        self._bump_confidence(other.confidence)

    def finalize(self) -> MetadataHints:
        if self.afn is None and self.di:
            derived = derive_afn_from_di(self.di)
            if derived is not None:
                self.afn = derived
                self.sources.append("di_derived_afn")
                if self.confidence == "low":
                    self.confidence = "medium"
        if self.afn is not None and self.di:
            if "di_derived_afn" not in self.sources and self.confidence == "low":
                self.confidence = "high"
        return self

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.di:
            missing.append("di")
        elif self.afn is None:
            missing.append("afn")
        return missing

    def ready_to_extend(self) -> bool:
        return bool(self.di)

    def _bump_confidence(self, level: str) -> None:
        order = {"low": 0, "medium": 1, "high": 2}
        if order.get(level, 0) > order.get(self.confidence, 0):
            self.confidence = level


def derive_afn_from_di(di: str) -> int | None:
    clean = di.upper().replace(" ", "")
    if len(clean) == 8 and clean.startswith("E8"):
        try:
            return int(clean[2:4], 16)
        except ValueError:
            return None
    return None


def _parse_afn(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    if text.upper().startswith("0X"):
        return int(text, 16)
    if re.search(r"[A-Fa-f]", text):
        return int(text, 16)
    return int(text, 10)


@dataclass
class DiRowParse:
    di: str
    title: str = ""
    afn: int | None = None
    afn_source: str = ""
    dir_hint: int | None = None
    add_hint: bool | None = None
    confidence: str = "medium"
    sources: list[str] = field(default_factory=list)


def normalize_di_token(raw: str) -> str | None:
    """Normalize DI from continuous, spaced, or partial token."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip().upper()
    spaced = _SPACED_DI.search(text)
    if spaced:
        parts = re.findall(r"[0-9A-Fa-f]{2}", spaced.group(0).upper())
        if len(parts) >= 4:
            return "".join(parts[:4])
    clean = text.replace(" ", "").replace("-", "")
    if len(clean) == 8 and clean.startswith("E8") and re.fullmatch(r"[0-9A-F]{8}", clean):
        return clean
    for pat in _DI_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).upper()
    return None


def merge_di_parts(*parts: str) -> str | None:
    """Merge E8 + three byte columns (DI3/DI2/DI1/DI0 style)."""
    cells = [str(p).strip().upper() for p in parts if str(p).strip()]
    if len(cells) < 4:
        return None
    if cells[0] != "E8":
        return None
    if not all(_HEX_BYTE.fullmatch(c) for c in cells[1:4]):
        return None
    return "".join(cells[:4])


def infer_afn_from_semantics(text: str, *, dir_hint: int | None = None) -> int | None:
    """Infer AFN from Chinese action words when DI/explicit AFN unavailable."""
    if not text:
        return None
    if re.search(r"上报", text):
        return 0x05
    if re.search(r"查询|读参数|请求", text):
        return 0x03
    if re.search(r"设置|写参数|配置|添加|删除|启动|停止|写", text):
        return 0x02
    if re.search(r"返回|响应|应答", text):
        return 0x04
    if dir_hint == 0:
        return 0x03
    if dir_hint == 1:
        return 0x05
    return None


def infer_dir_from_text(text: str) -> int | None:
    """Infer downlink/uplink from Chinese action words in title or table text."""
    if not text:
        return None
    if re.search(r"上行|响应|返回|应答|上报", text):
        return 1
    if re.search(r"下行|请求|查询|设置|添加|删除|启动|写参数|读参数", text):
        return 0
    return None


def infer_add_from_text(text: str) -> bool | None:
    if not text:
        return None
    if re.search(r"无地址|不带地址|地址域标识.*0", text):
        return False
    if re.search(r"带地址|有地址|地址域标识.*1", text):
        return True
    return None


def resolve_afn(
    *,
    di: str | None = None,
    afn: int | None = None,
    text: str = "",
    dir_hint: int | None = None,
) -> tuple[int | None, str]:
    """Resolve AFN: explicit > DI-derived > semantic."""
    if afn is not None:
        return afn, "explicit"
    if di:
        derived = derive_afn_from_di(di)
        if derived is not None:
            return derived, "di_derived"
    semantic = infer_afn_from_semantics(text, dir_hint=dir_hint)
    if semantic is not None:
        return semantic, "semantic"
    return None, ""


def extract_di_from_text(text: str, *, source: str = "text") -> MetadataHints:
    """Extract DI/AFN/dir from text including spaced DI forms."""
    hints = MetadataHints()
    if not text or not text.strip():
        return hints

    for pat in _AFN_PATTERNS:
        m = pat.search(text)
        if m:
            hints.afn = _parse_afn(m.group(1))
            hints.sources.append(source)
            hints.confidence = "high"
            break

    di = normalize_di_token(text)
    if di:
        hints.di = di
        hints.sources.append(source)
        hints.confidence = "high"

    if re.search(r"下行|请求", text):
        hints.dir_hint = 0
    elif re.search(r"上行|响应", text):
        hints.dir_hint = 1
    if re.search(r"无地址|不带地址", text):
        hints.add_hint = False
    elif re.search(r"带地址|有地址", text):
        hints.add_hint = True

    return hints.finalize()


def extract_from_text(text: str, *, source: str = "text") -> MetadataHints:
    return extract_di_from_text(text, source=source)


def _di_column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = header.strip().lower().replace(" ", "")
        if key in _DI_COL_KEYS or key.startswith("di"):
            mapping[key] = idx
        elif "di3" in key or header.strip().upper() == "DI3":
            mapping["di3"] = idx
        elif "di2" in key or header.strip().upper() == "DI2":
            mapping["di2"] = idx
        elif "di1" in key or header.strip().upper() == "DI1":
            mapping["di1"] = idx
        elif header.strip().upper() == "DI0":
            mapping["di0"] = idx
    return mapping


def _title_from_row(row: list[str], headers: list[str]) -> str:
    for idx, header in enumerate(headers):
        h = header.strip()
        if any(k in h for k in _TITLE_COL_KEYS) or "名称" in h:
            if idx < len(row) and row[idx].strip():
                text = row[idx].strip()
                if not normalize_di_token(text) and text.upper() != "E8":
                    return text
    di_idx: int | None = None
    for idx, cell in enumerate(row):
        if normalize_di_token(cell):
            di_idx = idx
            break
    if di_idx is not None:
        for cell in row[di_idx + 1:]:
            text = cell.strip()
            if not text:
                continue
            if normalize_di_token(text) or _HEX_BYTE.fullmatch(text):
                continue
            if text in {"0", "1", "新增", "已有", "原有", "CCO", "STA"}:
                continue
            return text
    for idx, cell in enumerate(row):
        if idx >= 3 and cell.strip() and not normalize_di_token(cell):
            if not _HEX_BYTE.fullmatch(cell.strip()) and cell.strip().upper() != "E8":
                if cell.strip() not in {"0", "1", "新增", "已有", "原有"}:
                    return cell.strip()
    return ""


def _dir_from_row(row: list[str], headers: list[str]) -> int | None:
    for idx, header in enumerate(headers):
        if any(k in header for k in _DIR_COL_KEYS):
            if idx < len(row):
                val = row[idx]
                if any(w in val for w in ("下行", "请求", "0")):
                    return 0
                if any(w in val for w in ("上行", "响应", "1")):
                    return 1
    for cell in row:
        if cell.strip() in {"下行", "上行"}:
            return 0 if cell.strip() == "下行" else 1
    return None


def extract_di_from_row(row: list[str], headers: list[str] | None = None) -> DiRowParse | None:
    """Extract DI from table row — supports multiple encodings."""
    if not row:
        return None
    headers = headers or []
    cells = [c.strip() for c in row]
    if cells[0].upper() in {"DI3", "D7", "DI"} and len(cells) >= 2:
        return None

    col_map = _di_column_map(headers)
    di: str | None = None
    sources: list[str] = []

    if len(col_map) >= 4:
        ordered = []
        for key in ("di3", "di2", "di1", "di0"):
            if key in col_map and col_map[key] < len(cells):
                ordered.append(cells[col_map[key]])
            else:
                ordered = []
                break
        if ordered:
            di = merge_di_parts(*ordered)
            if di:
                sources.append("di_columns")

    if di is None and cells[0].upper() == "E8" and len(cells) >= 4:
        di = merge_di_parts(*cells[:4])
        if di:
            sources.append("split_row")

    if di is None:
        for cell in cells:
            token = normalize_di_token(cell)
            if token:
                di = token
                sources.append("cell_di")
                break

    if di is None:
        blob = " ".join(cells)
        token = normalize_di_token(blob)
        if token:
            di = token
            sources.append("row_blob")

    if not di:
        return None

    title = _title_from_row(cells, headers)
    dir_hint = _dir_from_row(cells, headers)
    if dir_hint is None:
        blob_hints = extract_di_from_text(" ".join(cells))
        dir_hint = blob_hints.dir_hint

    afn, afn_source = resolve_afn(di=di, text=title or " ".join(cells), dir_hint=dir_hint)
    return DiRowParse(
        di=di,
        title=title,
        afn=afn,
        afn_source=afn_source,
        dir_hint=dir_hint,
        confidence="high" if "split_row" in sources or "di_columns" in sources else "medium",
        sources=sources,
    )


def extract_from_cell(text: str) -> MetadataHints:
    hints = MetadataHints()
    di = normalize_di_token(text)
    if di:
        hints.di = di
        hints.sources.append("cell_hex")
        hints.confidence = "medium"
    return hints.finalize()


def extract_from_kv_row(key: str, val: str) -> MetadataHints:
    hints = MetadataHints()
    key_l = key.strip().lower()
    val = val.strip()

    if any(k in key_l for k in _KV_AFN_KEYS):
        try:
            hints.afn = _parse_afn(val)
            hints.sources.append("table_kv_afn")
            hints.confidence = "high"
        except ValueError:
            pass
    elif any(k in key_l for k in _KV_DI_KEYS):
        di = normalize_di_token(val)
        if di:
            hints.di = di
            hints.sources.append("table_kv_di")
            hints.confidence = "high"
    elif any(k in key_l for k in _KV_DIR_KEYS):
        if any(w in val for w in ("下行", "请求", "0")):
            hints.dir_hint = 0
        elif any(w in val for w in ("上行", "响应", "1")):
            hints.dir_hint = 1
    elif any(k in key_l for k in _KV_ADD_KEYS):
        if any(w in val for w in ("无", "不带", "0", "false", "False")):
            hints.add_hint = False
        elif any(w in val for w in ("带", "有", "1", "true", "True")):
            hints.add_hint = True

    cell = extract_from_cell(val)
    hints.merge(cell)
    return hints.finalize()


def extract_from_table_rows(rows: list[list[str]], headers: list[str] | None = None) -> MetadataHints:
    hints = MetadataHints()
    for row in rows:
        parsed = extract_di_from_row(row, headers=headers)
        if parsed:
            row_hints = MetadataHints(
                di=parsed.di,
                afn=parsed.afn,
                dir_hint=parsed.dir_hint,
                add_hint=parsed.add_hint,
                confidence=parsed.confidence,
                sources=list(parsed.sources),
            )
            hints.merge(row_hints)
        if len(row) >= 2:
            kv = extract_from_kv_row(row[0], row[1])
            hints.merge(kv)
        blob = " ".join(row)
        text = extract_di_from_text(blob, source="table_row")
        hints.merge(text)
        for cell in row:
            hints.merge(extract_from_cell(cell))
    if hints.afn is None and hints.di:
        afn, _ = resolve_afn(di=hints.di, dir_hint=hints.dir_hint)
        if afn is not None:
            hints.afn = afn
            hints.sources.append("di_derived_afn")
    return hints.finalize()


def extract_afn_di_from_text(text: str) -> tuple[int | None, str | None]:
    """Backward-compatible wrapper."""
    h = extract_from_text(text)
    return h.afn, h.di
