"""Parse evidence text for value tables, units, keywords."""

from __future__ import annotations

import re
from typing import Any

_BOOL_KEYWORDS = ("开关", "使能", "是否", "启用", "禁止", "允许")
_RAW_KEYWORDS = ("透明数据", "保留", "厂家私有", "原始数据", "透明传输", "厂商自定义")
_ASCII_KEYWORDS = ("ascii", "字符串", "字符", "文本", "厂商代码", "厂商名")
_DECIMAL_UNITS = ("v", "a", "kw", "kwh", "hz", "℃", "°c", "c", "w", "wh", "%", "度", "伏", "安", "瓦")
_DATETIME_YMDHM = frozenset({"year", "month", "day", "hour", "minute", "年", "月", "日", "时", "分"})
_DATETIME_YMDHMS = _DATETIME_YMDHM | frozenset({"second", "秒"})

_HEX_LINE = re.compile(
    r"^\s*(?:0x)?([0-9A-Fa-f]{1,4})H?[：:\s]+(.+?)\s*$",
    re.IGNORECASE,
)
_DEC_LINE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
_UNIT_SCALE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([vVaA]|kW|kWh|Hz|℃|°C|%|W|Wh|度|伏|安|瓦)",
    re.IGNORECASE,
)
_RANGE = re.compile(r"范围\s*(\d+(?:\.\d+)?)\s*[~～\-—至到]\s*(\d+(?:\.\d+)?)")


def parse_value_table(texts: list[str]) -> dict[int, str]:
    values: dict[int, str] = {}
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _HEX_LINE.match(line)
            if m:
                values[int(m.group(1), 16)] = m.group(2).strip()
                continue
            m2 = _DEC_LINE.match(line)
            if m2:
                key = int(m2.group(1))
                if key not in values:
                    values[key] = m2.group(2).strip()
    return values


def has_value_table(texts: list[str]) -> bool:
    return bool(parse_value_table(texts))


def is_bool_value_table(values: dict[int, str], texts: list[str]) -> bool:
    if len(values) != 2:
        return False
    keys = sorted(values.keys())
    if keys == [0, 1]:
        return True
    blob = " ".join(texts).lower()
    if any(kw in blob for kw in _BOOL_KEYWORDS):
        labels = [values[k].lower() for k in keys]
        pairs = (
            ("关", "开"), ("关闭", "打开"), ("禁止", "允许"),
            ("否", "是"), ("off", "on"), ("false", "true"), ("0", "1"),
        )
        for a, b in pairs:
            if any(a in lbl for lbl in labels) and any(b in lbl for lbl in labels):
                return True
    return False


def has_named_states(texts: list[str]) -> bool:
    blob = " ".join(texts)
    state_words = ("状态", "类型", "模式", "类别", "运行", "设备类型")
    if not any(w in blob for w in state_words):
        return False
    # Lines like "单相表" "三相表" without hex prefix
    named = 0
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line or _HEX_LINE.match(line) or _DEC_LINE.match(line):
                continue
            if len(line) >= 2 and not line.startswith("0x"):
                named += 1
    return named >= 2


def parse_named_states(texts: list[str]) -> dict[int, str]:
    """Placeholder enum values when only names are given."""
    values: dict[int, str] = {}
    idx = 0
    for text in texts:
        for line in text.splitlines():
            line = line.strip().lstrip("-•* ")
            if not line or _HEX_LINE.match(line) or _DEC_LINE.match(line):
                continue
            if len(line) >= 2:
                values[idx] = line
                idx += 1
    return values


def mentions_raw(texts: list[str]) -> bool:
    blob = " ".join(texts).lower()
    return any(kw in blob for kw in _RAW_KEYWORDS)


def mentions_ascii(texts: list[str]) -> bool:
    blob = " ".join(texts).lower()
    return any(kw in blob for kw in _ASCII_KEYWORDS)


def parse_unit_scale(texts: list[str]) -> tuple[str | None, float | None]:
    unit: str | None = None
    scale: float | None = None
    blob = " ".join(texts)
    m = _UNIT_SCALE.search(blob)
    if m:
        scale = float(m.group(1))
        raw_unit = m.group(2)
        unit_map = {"伏": "V", "安": "A", "瓦": "W", "度": "kWh"}
        unit = unit_map.get(raw_unit, raw_unit.upper() if len(raw_unit) <= 3 else raw_unit)
    if "0.1" in blob and not scale:
        scale = 0.1
    if "0.01" in blob and not scale:
        scale = 0.01
    return unit, scale


def parse_range(texts: list[str]) -> tuple[float | None, float | None]:
    for text in texts:
        m = _RANGE.search(text)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None, None


_CORE_YMDHMS = frozenset({"year", "month", "day", "hour", "minute", "second"})
_CORE_YMDHM = frozenset({"year", "month", "day", "hour", "minute"})


def detect_datetime_alias(subfields: list[Any]) -> str | None:
    names: set[str] = set()
    for f in subfields:
        if hasattr(f, "name"):
            raw = str(f.name)
        elif isinstance(f, dict):
            raw = str(f.get("name", ""))
        else:
            raw = ""
        names.add(raw.lower())
    cn_map = {"年": "year", "月": "month", "日": "day", "时": "hour", "分": "minute", "秒": "second"}
    normalized = {cn_map.get(n, n) for n in names}
    if _CORE_YMDHMS.issubset(normalized):
        return "datetime_ymdhms"
    if _CORE_YMDHM.issubset(normalized):
        return "datetime_ymdhm"
    return None


def enum_byte_length(values: dict[int, str], declared_bytes: int | None) -> int:
    if declared_bytes:
        return declared_bytes
    max_key = max(values.keys()) if values else 0
    if max_key <= 0xFF:
        return 1
    if max_key <= 0xFFFF:
        return 2
    return 4


def integer_codec_type(byte_width: int | None) -> str:
    if byte_width == 1:
        return "uint8"
    if byte_width == 2:
        return "uint16_le"
    if byte_width == 3:
        return "uint24_le"
    if byte_width == 4:
        return "uint32_le"
    return "uint8"


def decimal_codec(byte_width: int | None, unit: str | None) -> dict[str, Any]:
    length = byte_width or 2
    fmt = "XXX.X" if length == 2 else "XXXXXX.XX" if length == 4 else "XXX.XXX"
    codec: dict[str, Any] = {
        "type": "bcd_numeric",
        "length": length,
        "format": fmt,
        "signed": False,
    }
    if unit:
        codec["unit"] = unit
    return codec
