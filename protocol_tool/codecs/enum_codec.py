"""Enum codec — decodes integer values to named constants."""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class EnumValueError(ValueError):
    """Raised when an enum input cannot be mapped to schema values."""


class EnumCodec(FieldCodec):
    """Decodes an integer and maps it to a named value.

    Parameters (from FieldNode.params):
        values: dict mapping int values to string labels
            e.g. {0: "ok", 1: "error", 2: "timeout"}
        length: byte length of the wire value (default 1)
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> dict[str, Any]:
        length = self.field_length(field, context) or 1
        raw = reader.read(length)
        raw_int = int.from_bytes(raw, "big")

        values = _normalize_enum_values(field.params.get("values", {}))
        label = values.get(raw_int, f"unknown_{raw_int:02X}")

        return {"raw": raw_int, "label": label}

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        length = self.field_length(field, context) or 1
        values = field.params.get("values", {})
        raw_int = resolve_enum_raw(value, values, field_name=field.name)
        writer.write(raw_int.to_bytes(length, "big"))


def resolve_enum_raw(
    value: Any,
    values: dict[Any, Any],
    *,
    field_name: str = "",
) -> int:
    """Map user input to wire integer; raise EnumValueError when invalid."""
    normalized = _normalize_enum_values(values)
    prefix = f"{field_name}: " if field_name else ""

    if not normalized:
        return int(value)

    if isinstance(value, dict):
        if "raw" in value:
            raw_int = int(value["raw"])
            return _require_known_raw(raw_int, normalized, prefix)
        if "label" in value:
            label = value["label"]
            for raw_int, name in normalized.items():
                if name == label:
                    return raw_int
            raise EnumValueError(
                f"{prefix}invalid enum label {label!r}; allowed: {_format_allowed_values(normalized)}"
            )
        raise EnumValueError(
            f"{prefix}invalid enum object {value!r}; use raw, label, or a scalar value"
        )

    if isinstance(value, str):
        parsed = _parse_enum_text(value, values)
        if parsed is not None:
            return _require_known_raw(parsed, normalized, prefix)
        for raw_int, name in normalized.items():
            if name == value:
                return raw_int
        raise EnumValueError(
            f"{prefix}invalid enum value {value!r}; allowed: {_format_allowed_values(normalized)}"
        )

    raw_int = int(value)
    return _require_known_raw(raw_int, normalized, prefix)


def _require_known_raw(raw_int: int, normalized: dict[int, str], prefix: str) -> int:
    if raw_int not in normalized:
        raise EnumValueError(
            f"{prefix}unknown enum value 0x{raw_int:02X}; allowed: {_format_allowed_values(normalized)}"
        )
    return raw_int


def _format_allowed_values(normalized: dict[int, str]) -> str:
    return ", ".join(
        f"0x{raw:02X}({label})" for raw, label in sorted(normalized.items())
    )


def _normalize_enum_values(values: dict[Any, Any]) -> dict[int, str]:
    return {_enum_key_to_int(key): str(label) for key, label in values.items()}


def _enum_key_to_int(key: Any) -> int:
    if isinstance(key, int):
        return key
    text = str(key).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if re.fullmatch(r"[0-9A-Fa-f]{2}", text):
        return int(text, 16)
    return int(text, 10)


def _parse_enum_text(text: str, values: dict[Any, Any]) -> int | None:
    compact = re.sub(r"\s+", "", text.strip())
    if not compact:
        return None
    if re.fullmatch(r"0x[0-9A-Fa-f]+", compact, re.IGNORECASE):
        return int(compact, 16)
    if re.fullmatch(r"[0-9A-Fa-f]{2}", compact):
        return int(compact, 16)
    if compact.isdigit():
        return int(compact, 10)
    for key in values:
        if str(key).lower() == compact.lower():
            return _enum_key_to_int(key)
    normalized = _normalize_enum_values(values)
    if compact in {str(v) for v in normalized.values()}:
        return next(k for k, v in normalized.items() if v == compact)
    return None
