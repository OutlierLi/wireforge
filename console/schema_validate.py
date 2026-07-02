"""Validate user business values against /route input_schema."""

from __future__ import annotations

import re
from typing import Any

from console.build_resolver import InputField
from protocol_tool.codecs.enum_codec import EnumValueError, resolve_enum_raw

_UINT_LIMITS: dict[str, tuple[int, int]] = {
    "uint8": (0, 0xFF),
    "uint16_le": (0, 0xFFFF),
    "uint16_be": (0, 0xFFFF),
    "uint24_le": (0, 0xFFFFFF),
    "uint32_le": (0, 0xFFFFFFFF),
    "uint32_be": (0, 0xFFFFFFFF),
}

_HEX_LIKE_TYPES = frozenset({"hex", "bytes", "bcd"})
_UINT_TYPES = frozenset(_UINT_LIMITS)
_SCALAR_TYPES = _UINT_TYPES | _HEX_LIKE_TYPES | frozenset({"ascii", "bcd_numeric", "enum"})


def validate_business_values(
    user_values: dict[str, Any],
    input_schema: list[InputField],
) -> list[str]:
    """Return human-readable validation errors; empty list means OK."""
    from console.arg_utils import coerce_business_values

    try:
        user_values = coerce_business_values(dict(user_values), input_schema)
    except ValueError as exc:
        return [str(exc)]

    schema_by_name = {field.name: field for field in input_schema}
    errors: list[str] = []
    for name, value in user_values.items():
        field = schema_by_name.get(name)
        if field is None:
            continue
        errors.extend(_validate_field_value(field, value, name))
    return errors


def _validate_field_value(field: InputField, value: Any, path: str) -> list[str]:
    ftype = field.type
    if ftype == "enum":
        return _validate_enum(field, value, path)
    if ftype == "array":
        return _validate_array(field, value, path)
    if ftype == "struct":
        return _validate_struct(field, value, path)
    if ftype in _SCALAR_TYPES:
        return _validate_scalar(field, value, path)
    return []


def _validate_scalar(field: InputField, value: Any, path: str) -> list[str]:
    ftype = field.type
    if ftype in _UINT_TYPES:
        return _validate_uint(field, value, path)
    if ftype in _HEX_LIKE_TYPES:
        return _validate_hex_like(field, value, path, ftype)
    if ftype == "ascii":
        return _validate_ascii(field, value, path)
    if ftype == "bcd_numeric":
        return _validate_bcd_numeric(field, value, path)
    if ftype == "enum":
        return _validate_enum(field, value, path)
    return []


def _validate_enum(field: InputField, value: Any, path: str) -> list[str]:
    values = field.enum_values or {}
    if not values:
        return []
    try:
        resolve_enum_raw(value, values, field_name=path)
    except EnumValueError as exc:
        return [str(exc)]
    return []


def _validate_uint(field: InputField, value: Any, path: str) -> list[str]:
    try:
        number = _parse_int(value)
    except (TypeError, ValueError):
        return [f"{path}: expected number for {field.type}, got {value!r}"]
    limits = _UINT_LIMITS.get(field.type)
    if limits and not limits[0] <= number <= limits[1]:
        lo, hi = limits
        return [f"{path}: {field.type} out of range [{lo}, {hi}], got {number}"]
    return []


def _validate_hex_like(field: InputField, value: Any, path: str, type_name: str) -> list[str]:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        compact, err = _normalize_hex_input(value)
        if err:
            return [f"{path}: expected hex digit string for {type_name}, {err}"]
        assert compact is not None
        if type_name in ("hex", "bytes") and len(compact) % 2:
            return [f"{path}: hex string must have an even number of digits"]
        try:
            raw = bytes.fromhex(compact if len(compact) % 2 == 0 else f"0{compact}")
        except ValueError:
            return [f"{path}: invalid hex string for {type_name}: {value!r}"]
        if type_name == "bcd" and field.length is not None and len(compact) > field.length * 2:
            return [
                f"{path}: bcd value too long (max {field.length * 2} hex digits)"
            ]
        return []
    elif isinstance(value, int):
        if type_name != "bcd":
            return [f"{path}: expected hex string for {type_name}, got int"]
        text = f"{value:X}"
        if field.length and len(text) > field.length * 2:
            return [f"{path}: bcd value too long (max {field.length * 2} hex digits)"]
        return []
    else:
        return [f"{path}: expected hex string for {type_name}, got {type(value).__name__}"]

    if field.length is not None and len(raw) > field.length:
        if type_name == "bcd":
            return [
                f"{path}: bcd value too long (max {field.length * 2} hex digits)"
            ]
        return [
            f"{path}: {type_name} too long (max {field.length} bytes, got {len(raw)})"
        ]
    return []


def _validate_ascii(field: InputField, value: Any, path: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{path}: expected string for ascii, got {type(value).__name__}"]
    if field.length is not None and len(value) > field.length:
        return [f"{path}: ascii too long (max {field.length} chars, got {len(value)})"]
    return []


def _validate_bcd_numeric(field: InputField, value: Any, path: str) -> list[str]:
    text = str(value).strip().replace(" ", "")
    if not text:
        return [f"{path}: expected numeric string for bcd_numeric, got empty value"]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return [f"{path}: invalid bcd_numeric value {value!r}"]
    return []


def _validate_array(field: InputField, value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{path}: expected list for array field, got {type(value).__name__}"]
    if not field.children:
        return []

    errors: list[str] = []
    struct_items = len(field.children) > 1

    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if isinstance(item, dict):
            for child in field.children:
                if child.name not in item:
                    continue
                errors.extend(
                    _validate_field_value(child, item[child.name], f"{item_path}.{child.name}")
                )
            continue
        if struct_items:
            errors.append(
                f"{item_path}: expected object for struct array item, got {type(item).__name__}"
            )
            continue
        if len(field.children) == 1:
            errors.extend(_validate_field_value(field.children[0], item, item_path))
    return errors


def _validate_struct(field: InputField, value: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected object for struct field, got {type(value).__name__}"]
    errors: list[str] = []
    for child in field.children:
        if child.name not in value:
            continue
        errors.extend(_validate_field_value(child, value[child.name], f"{path}.{child.name}"))
    return errors


def _parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("bool is not a valid integer field value")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "")
        if not text:
            raise ValueError("empty string")
        if re.fullmatch(r"0x[0-9A-Fa-f]+", text):
            return int(text, 16)
        if re.fullmatch(r"-?\d+", text):
            return int(text, 10)
    raise ValueError(f"cannot parse int from {value!r}")


def _normalize_hex_input(value: str) -> tuple[str | None, str | None]:
    compact = re.sub(r"\s+", "", value.strip())
    if not compact:
        return None, "got empty value"
    if not re.fullmatch(r"[0-9A-Fa-f]+", compact):
        return None, f"invalid hex digits: {value!r}"
    return compact.upper(), None
