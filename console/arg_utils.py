"""CLI 参数规范化 — 引号剥离、hex 合并。"""

from __future__ import annotations

import re
from typing import Any

QUOTE_CHARS = frozenset('"\'“”')
HEX_MERGE_KEYS = frozenset({"hex", "from_frame", "from-frame"})

_HEX_TOKEN_RE = re.compile(r"^[0-9A-Fa-f]+$")


def strip_nested_quotes(value: str) -> str:
    """Remove matching quote pairs from both ends until stable."""
    raw = value.strip()
    while len(raw) >= 2 and raw[0] in QUOTE_CHARS and raw[-1] in QUOTE_CHARS:
        raw = raw[1:-1].strip()
    return raw


def looks_like_hex_token(value: str) -> bool:
    token = strip_nested_quotes(str(value).strip())
    return bool(token) and _HEX_TOKEN_RE.fullmatch(token) is not None


def parse_bracket_list(value: str) -> list[str] | None:
    """Parse CLI bracket list syntax: ``[a, b, c]`` → ``['a', 'b', 'c']``."""
    raw = strip_nested_quotes(value.strip())
    if not raw.startswith("[") or not raw.endswith("]"):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    for part in inner.split(","):
        part = strip_nested_quotes(part.strip())
        if part:
            items.append(part)
    return items


def looks_like_open_bracket_list(value: str) -> bool:
    raw = strip_nested_quotes(str(value).strip())
    return raw.startswith("[") and not raw.endswith("]")


def merge_bracket_list_value_tail(
    value: str,
    parts: list[str],
    index: int,
) -> tuple[str, int]:
    """``--slave_addrs [a, b]`` 被 shlex 按逗号/空格拆段时，向后合并至 ``]``。"""
    if not looks_like_open_bracket_list(value):
        return value, index

    merged = [value]
    j = index + 1
    while j < len(parts):
        if parts[j].startswith("--"):
            break
        merged.append(parts[j])
        if parts[j].rstrip().endswith("]"):
            break
        j += 1
    return " ".join(merged), j


def looks_like_open_bracket_assignment(value: str) -> bool:
    """``--set slave_addrs=[a,`` 等 ``field=[...`` 未闭合赋值。"""
    raw = strip_nested_quotes(str(value).strip())
    if "=" not in raw or raw.endswith("]"):
        return False
    _, rhs = raw.split("=", 1)
    rhs = rhs.strip()
    return rhs.startswith("[") and not rhs.endswith("]")


def merge_bracket_assignment_value_tail(
    value: str,
    parts: list[str],
    index: int,
) -> tuple[str, int]:
    """``--set slave_addrs=[a, b]`` 被 shlex 在逗号处拆段时，向后合并至 ``]``。"""
    if not looks_like_open_bracket_assignment(value):
        return value, index

    merged = [value]
    j = index + 1
    while j < len(parts):
        if parts[j].startswith("--"):
            break
        merged.append(parts[j])
        if parts[j].rstrip().endswith("]"):
            break
        j += 1
    return " ".join(merged), j


def merge_split_value_tail(
    value: str,
    parts: list[str],
    index: int,
) -> tuple[str, int]:
    """合并被 shlex 拆开的 ``[...]`` 或 ``field=[...]`` 参数值。"""
    if looks_like_open_bracket_list(value):
        return merge_bracket_list_value_tail(value, parts, index)
    if looks_like_open_bracket_assignment(value):
        return merge_bracket_assignment_value_tail(value, parts, index)
    return value, index


def coerce_array_value(value: Any) -> list[Any] | None:
    """Normalize array CLI/YAML values; parse ``[a, b]`` strings into lists."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = parse_bracket_list(value)
        if parsed is not None:
            return parsed
    return None


def clean_string_arg(value: Any, *, key: str = "") -> Any:
    if not isinstance(value, str):
        return value
    stripped = strip_nested_quotes(value)
    parsed = parse_bracket_list(stripped)
    if parsed is not None:
        return parsed
    return stripped


def compact_hex(text: str) -> str:
    return strip_nested_quotes(str(text)).replace(" ", "").replace("\n", "")


def normalize_hex_from_args(args: dict[str, Any], *, key: str = "hex") -> str:
    """合并 hex 主值与后续 hex 片段（含 positional `_` 中的连续 hex token）。"""
    chunks: list[str] = []
    primary = args.get(key)
    if primary not in (None, "", False):
        chunks.append(str(primary))

    for token in args.get("_") or []:
        if not looks_like_hex_token(token):
            break
        chunks.append(str(token))

    if not chunks:
        return ""

    return "".join(compact_hex(part) for part in chunks)


def merge_quoted_value_tail(value: str, parts: list[str], index: int) -> tuple[str, int]:
    """posix=False 下 `--hex=\"68 0C ...\"` 被拆段时，向后合并至闭合引号。"""
    if not value:
        return value, index

    opener = value[0] if value[0] in QUOTE_CHARS else None
    if opener is None:
        return value, index

    if value.endswith(opener) and len(value) > 1:
        return value, index

    merged = [value]
    j = index + 1
    while j < len(parts):
        merged.append(parts[j])
        if parts[j].endswith(opener):
            break
        j += 1
    return " ".join(merged), j


def parse_timeout_ms(value: Any, default: int = 5000) -> int:
    """Parse timeout to milliseconds. Supports ``5000``, ``5s``, ``500ms``."""
    if value is None or value == "":
        return default
    s = str(value).strip().lower()
    if s.endswith("ms"):
        return int(float(s[:-2].strip()))
    if s.endswith("s"):
        return int(float(s[:-1].strip()) * 1000)
    return int(float(s))


def merge_hex_value_tail(value: str, parts: list[str], index: int) -> tuple[str, int]:
    """`--hex 68 0C 00` 无引号时，吞并后续 hex token。"""
    if not looks_like_hex_token(value):
        return value, index

    merged = [value]
    j = index + 1
    while j < len(parts) and not parts[j].startswith("--") and looks_like_hex_token(parts[j]):
        merged.append(parts[j])
        j += 1
    return " ".join(merged), j - 1
