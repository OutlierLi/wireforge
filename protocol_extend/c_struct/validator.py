"""Validate parsed C struct definitions."""

from __future__ import annotations

import re

from protocol_extend.c_struct.ir import CFieldDef, CStructDef
from protocol_extend.c_struct.parser import CStructParseError

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_c_struct(defn: CStructDef, *, allow_empty: bool = True) -> list[str]:
    """Return validation warnings (empty struct allowed for zero-byte payloads)."""
    warnings: list[str] = []
    if not defn.fields:
        if not allow_empty:
            raise CStructParseError("struct has no fields", path=defn.source_path)
        return warnings

    _validate_fields(defn.fields, warnings, path=defn.source_path)
    return warnings


def _validate_fields(
    fields: list[CFieldDef],
    warnings: list[str],
    *,
    path: str | None,
    prior_names: list[str] | None = None,
) -> None:
    seen: set[str] = set()
    prior = list(prior_names or [])
    for field in fields:
        _validate_field(field, seen, prior, warnings, path=path)
        prior.append(field.name)


def _validate_field(
    field: CFieldDef,
    seen: set[str],
    prior_names: list[str],
    warnings: list[str],
    *,
    path: str | None,
) -> None:
    if not field.name:
        raise CStructParseError("field missing name", line=field.line, path=path)
    if not _NAME_RE.match(field.name):
        raise CStructParseError(f"invalid field name: {field.name}", line=field.line, path=path)
    key = field.name.lower()
    if key in seen:
        raise CStructParseError(f"duplicate field name: {field.name}", line=field.line, path=path)
    seen.add(key)

    if field.is_flexible_array:
        ref = field.annotations.count_ref or field.annotations.length_ref
        if not ref:
            raise CStructParseError(
                f"array '{field.name}' missing @count_ref or @length_ref",
                line=field.line,
                path=path,
            )
        if field.annotations.count_ref and ref not in prior_names:
            raise CStructParseError(
                f"@count_ref '{ref}' must refer to a prior field",
                line=field.line,
                path=path,
            )
        if field.annotations.length_ref and ref not in prior_names:
            raise CStructParseError(
                f"@length_ref '{ref}' must refer to a prior field",
                line=field.line,
                path=path,
            )
    elif field.wire_size is None and not field.subfields:
        warnings.append(f"{field.name}: unknown wire size for type {field.c_type}")

    if field.annotations.enum_values and len(field.annotations.enum_values) < 2:
        warnings.append(f"{field.name}: enum needs at least 2 values")

    if field.subfields:
        _validate_fields(field.subfields, warnings, path=path, prior_names=prior_names)
