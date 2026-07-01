"""Parse WireForge C struct DSL into CStructDef."""

from __future__ import annotations

import re
from pathlib import Path

from protocol_extend.c_struct.ir import (
    CFieldAnnotations,
    CFieldDef,
    CStructDef,
    CStructMetadata,
)
from protocol_extend.c_struct.type_map import wire_size_for_scalar
from protocol_extend.schema import normalize_afn, normalize_di, normalize_dir, normalize_add, normalize_func

_WIREFORGE_META = re.compile(
    r"@wireforge\b(.*?)(?:\*/|$)",
    re.I | re.S,
)
_META_KV = re.compile(
    r"(\w+)\s*=\s*(\"([^\"]*)\"|'([^']*)'|(\S+))",
)
_FIELD_COMMENT = re.compile(r"/\*(.*?)\*/", re.S)
_TYPEDEF_STRUCT = re.compile(
    r"typedef\s+struct\s+(?:__attribute__\s*\(\(\s*packed\s*\)\)\s*)?\{(?P<body>.*)\}\s*(?P<name>\w+)\s*;",
    re.S,
)
_BARE_STRUCT = re.compile(
    r"struct\s+(?:__attribute__\s*\(\(\s*packed\s*\)\)\s*)?\{(?P<body>.*)\}\s*(?P<name>\w+)\s*;",
    re.S,
)
_NESTED_STRUCT = re.compile(
    r"^struct\s*\{(?P<body>.*)\}\s*(?P<name>\w+)"
    r"(?:\[\s*(?P<array_size>\d+)?\s*\])?"
    r"\s*;?\s*(?P<tail>/\*.*)?$",
    re.S,
)
_SIMPLE_FIELD = re.compile(
    r"^(?P<type>[\w]+(?:_t)?)\s+(?P<name>\w+)"
    r"(?:\[\s*(?P<size>\d+)?\s*\])?"
    r"\s*(?P<tail>.*?)$",
    re.S,
)
_ANNOTATION = re.compile(r"@(\w+)(?:\s+([^@*]+))?")


class CStructParseError(ValueError):
    def __init__(self, message: str, *, line: int | None = None, path: str | None = None) -> None:
        loc = []
        if path:
            loc.append(path)
        if line is not None:
            loc.append(f"line {line}")
        prefix = ": ".join(loc)
        super().__init__(f"{prefix}: {message}" if prefix else message)
        self.line = line
        self.path = path


def parse_c_struct(source: str, *, path: str | None = None) -> CStructDef:
    text = source.replace("\r\n", "\n").strip()
    if not text:
        raise CStructParseError("empty C struct source", path=path)

    metadata = _parse_metadata(text)
    struct_match = _TYPEDEF_STRUCT.search(text) or _BARE_STRUCT.search(text)
    if not struct_match:
        raise CStructParseError("expected typedef struct { ... } name;", path=path)

    body = struct_match.group("body")
    name = struct_match.group("name")
    fields = _parse_struct_body(body, path=path)
    _assign_layout(fields)

    return CStructDef(
        name=name,
        metadata=metadata,
        fields=fields,
        source_path=path,
        packed=True,
    )


def _parse_metadata(text: str) -> CStructMetadata:
    meta = CStructMetadata()
    for block in _WIREFORGE_META.finditer(text):
        blob = block.group(1)
        for match in _META_KV.finditer(blob):
            key = match.group(1).lower()
            value = match.group(3) or match.group(4) or match.group(5) or ""
            if key == "afn":
                meta.afn = normalize_afn(value)
            elif key == "func":
                meta.func = normalize_func(value)
            elif key == "di":
                meta.di = normalize_di(value)
            elif key == "dir":
                meta.dir = normalize_dir(value)
            elif key == "add":
                meta.add = normalize_add(value)
            elif key == "desc":
                meta.description = value.strip()
            elif key == "description":
                meta.description = value.strip()
            elif key == "pair":
                meta.pair = str(value).lower() in {"1", "true", "yes"}
            elif key == "resp_description":
                meta.resp_description = value.strip()
    return meta


def _parse_struct_body(body: str, *, path: str | None) -> list[CFieldDef]:
    normalized = _normalize_trailing_comments(body)
    segments = _split_top_level(normalized, delimiter=";")
    fields: list[CFieldDef] = []
    line_base = 1

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        line = line_base + body[: body.find(segment.split(";")[0])].count("\n") if segment in body else line_base
        line_base = line + segment.count("\n")

        nested = _NESTED_STRUCT.match(segment)
        if nested:
            sub_body = nested.group("body")
            sub_name = nested.group("name")
            tail = nested.group("tail") or ""
            subfields = _parse_struct_body(sub_body, path=path)
            ann = _parse_annotations(tail)
            array_size_text = nested.group("array_size")
            has_array = re.search(
                rf"\}}\s*{re.escape(sub_name)}\s*\[",
                segment,
            ) is not None

            if has_array and array_size_text is None:
                if not ann.count_ref and not ann.length_ref:
                    raise CStructParseError(
                        f"flexible array '{sub_name}' requires @count_ref or @length_ref",
                        line=line,
                        path=path,
                    )
                fields.append(
                    CFieldDef(
                        name=sub_name,
                        c_type="struct",
                        annotations=ann,
                        subfields=subfields,
                        is_flexible_array=True,
                        wire_size=None,
                        line=line,
                    )
                )
                continue

            if has_array and array_size_text is not None:
                raise CStructParseError(
                    f"fixed-size struct array '{sub_name}' is not supported; use @count_ref flex array",
                    line=line,
                    path=path,
                )

            wire = sum(sf.wire_size or 0 for sf in subfields)
            fields.append(
                CFieldDef(
                    name=sub_name,
                    c_type="struct",
                    annotations=ann,
                    subfields=subfields,
                    wire_size=wire or None,
                    line=line,
                )
            )
            continue

        match = _SIMPLE_FIELD.match(segment)
        if not match:
            raise CStructParseError(f"unsupported field syntax: {segment!r}", line=line, path=path)

        c_type = match.group("type").strip()
        name = match.group("name").strip()
        size_text = match.group("size")
        tail = match.group("tail") or ""
        ann = _parse_annotations(tail)

        array_size: int | None = None
        is_flex = False
        array_match = re.search(r"\[\s*(\d+)?\s*\]", segment)
        if array_match:
            if array_match.group(1) is not None:
                array_size = int(array_match.group(1))
            else:
                is_flex = True
                if not ann.count_ref and not ann.length_ref:
                    raise CStructParseError(
                        f"flexible array '{name}' requires @count_ref or @length_ref",
                        line=line,
                        path=path,
                    )

        wire = wire_size_for_scalar(c_type, array_size=array_size)
        if ann.domain == "node_address" or c_type in {"node_address_t", "node_address"}:
            wire = 6

        fields.append(
            CFieldDef(
                name=name,
                c_type=c_type,
                array_size=array_size,
                is_flexible_array=is_flex,
                annotations=ann,
                wire_size=wire,
                line=line,
            )
        )
    return fields


def _normalize_trailing_comments(body: str) -> str:
    """Move ``; /* comment */`` to ``/* comment */ ;`` so semicolon splits stay field-aligned."""
    return re.sub(r";\s*(/\*.*?\*/)", r" \1;", body, flags=re.S)


def _split_top_level(text: str, *, delimiter: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_annotations(tail: str) -> CFieldAnnotations:
    ann = CFieldAnnotations()
    comment_match = _FIELD_COMMENT.search(tail)
    if not comment_match:
        return ann

    blob = comment_match.group(1)
    for match in _ANNOTATION.finditer(blob):
        key = match.group(1).lower()
        rest = (match.group(2) or "").strip()
        if key == "desc":
            ann.desc = rest
        elif key == "enum":
            ann.enum_values = _parse_enum_values(rest)
        elif key == "domain":
            ann.domain = rest.split()[0] if rest else ""
        elif key == "alias":
            ann.alias = rest.split()[0] if rest else ""
        elif key == "unit":
            ann.unit = rest
        elif key == "scale":
            try:
                ann.scale = float(rest.split()[0])
            except (TypeError, ValueError):
                pass
        elif key == "count_ref":
            ann.count_ref = rest.split()[0] if rest else ""
        elif key == "length_ref":
            ann.length_ref = rest.split()[0] if rest else ""
        elif key == "item_name":
            ann.item_name = rest.split()[0] if rest else ""
        elif key == "default":
            ann.default = rest.split()[0] if rest else rest
        elif key == "hex":
            ann.hex_type = True
        else:
            ann.raw[key] = rest
    return ann


def _parse_enum_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in re.split(r"\s+", text.strip()):
        if not part or ":" not in part and "：" not in part:
            continue
        sep = ":" if ":" in part else "："
        key, label = part.split(sep, 1)
        key = key.strip()
        if key.lower().endswith("h"):
            key = f"0x{key[:-1]}"
        elif key.isdigit():
            key = f"0x{int(key):02X}"
        elif key.lower().startswith("0x"):
            key = key.lower()
        values[key] = label.strip()
    return values


def _assign_layout(fields: list[CFieldDef]) -> None:
    offset = 0
    for field in fields:
        field.offset = offset
        if field.is_flexible_array:
            field.wire_size = None
            continue
        if field.subfields:
            _assign_layout(field.subfields)
            field.wire_size = sum(sf.wire_size or 0 for sf in field.subfields)
        if field.wire_size is not None:
            offset += field.wire_size


def read_c_struct_file(path: str | Path, *, root: Path | None = None) -> tuple[str, str]:
    p = Path(path)
    if not p.is_absolute() and root is not None:
        candidate = root / p
        if candidate.exists():
            p = candidate
    if not p.exists():
        raise FileNotFoundError(f"C struct file not found: {path}")
    return p.read_text(encoding="utf-8"), str(p)
