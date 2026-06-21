"""BCD (Binary-Coded Decimal) codecs.

Supports:
- Plain BCD: each nibble is a hex digit, output as string
- BCD Numeric: domain-specific types (energy, voltage, etc.) with format strings
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class BcdCodec(FieldCodec):
    """Plain BCD decoder: bytes → hex digit string.

    Parameters (from FieldNode.params):
        length: byte length (required unless length_from is set)
        byte_order: "little" (reverse on wire) or "big" (native)
        canonical_format: "decimal_string" (strip leading zeros) or None (raw hex)
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> str:
        length = self.field_length(field, context)
        if length is None:
            raise ValueError(f"BCD field {field.name!r} requires explicit length")
        raw = reader.read(length)

        # Byte order
        byte_order = field.params.get("byte_order", "big")
        if byte_order in ("little", "little_endian", "reverse"):
            raw = raw[::-1]

        # Decode nibbles
        digits: list[str] = []
        for byte in raw:
            digits.extend([f"{(byte >> 4) & 0x0F:X}", f"{byte & 0x0F:X}"])
        result = "".join(digits)

        # Canonical format
        fmt = field.params.get("canonical_format", "")
        if fmt == "decimal_string":
            result = result.lstrip("0") or "0"

        return result

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        length = self.field_length(field, context)
        if length is None:
            raise ValueError(f"BCD field {field.name!r} requires explicit length")

        text = str(value).strip().upper()
        # Remove whitespace and non-hex chars
        text = "".join(ch for ch in text if ch in "0123456789ABCDEF")

        expected_digits = length * 2
        if len(text) < expected_digits:
            text = text.zfill(expected_digits)
        elif len(text) > expected_digits:
            raise ValueError(
                f"BCD value too long for field {field.name!r}: "
                f"{len(text)} digits, max {expected_digits}"
            )

        raw = bytes(
            (int(text[i], 16) << 4) | int(text[i + 1], 16)
            for i in range(0, len(text), 2)
        )

        # Byte order
        byte_order = field.params.get("byte_order", "big")
        if byte_order in ("little", "little_endian", "reverse"):
            raw = raw[::-1]

        writer.write(raw)


# Domain-specific BCD numeric type metadata
# Ported from old project's BCD_NUMERIC_FIELD_TYPES
BCD_NUMERIC_TYPES: dict[str, dict[str, Any]] = {
    "energy_4": {"length": 4, "format": "XXXXXX.XX", "unit": "kWh", "signed": False},
    "energy_5": {"length": 5, "format": "XXXXXX.XXXX", "unit": "kWh", "signed": False},
    "demand_4": {"length": 4, "format": "XX.XXXX", "unit": "kW", "signed": True},
    "voltage_2": {"length": 2, "format": "XXX.X", "unit": "V", "signed": False},
    "current_3": {"length": 3, "format": "XXX.XXX", "unit": "A", "signed": True},
    "power_3": {"length": 3, "format": "XX.XXXX", "unit": "kW", "signed": True},
    "power_factor_2": {"length": 2, "format": "X.XXX", "signed": True},
    "angle_2": {"length": 2, "format": "XXX.X", "unit": "degree", "signed": False},
    "frequency_2": {"length": 2, "format": "XX.XX", "unit": "Hz", "signed": False},
    "temperature_2": {"length": 2, "format": "XXX.X", "unit": "℃", "signed": True},
    "percent_2": {"length": 2, "format": "XX.XX", "unit": "%", "signed": False},
}


class BcdNumericCodec(FieldCodec):
    """Domain-specific BCD numeric decoder (energy, voltage, etc.).

    Parameters (from FieldNode.params):
        type_name: key into BCD_NUMERIC_TYPES (e.g. "energy_4")
        length: override byte length
        format: override display format (e.g. "XXXXXX.XX")
        unit: override unit string
        signed: override signed flag
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> dict[str, Any]:
        type_name = field.params.get("type_name", "")
        meta = dict(BCD_NUMERIC_TYPES.get(type_name, {}))
        meta.update(field.params)

        length = field.length or meta.get("length", 4)
        raw = bytearray(reader.read(length))

        negative = False
        if meta.get("signed"):
            negative = bool(raw[0] & 0x80)
            raw[0] &= 0x7F

        # Decode as plain BCD
        bcd = BcdCodec().decode(
            field.__class__(
                id=field.id,
                name=field.name,
                type_ref="bcd",
                params={"byte_order": "big"},
                length=length,
            ),
            _FakeReader(bytes(raw)),
            context,
        )

        if any(ch not in "0123456789" for ch in bcd):
            raise ValueError(
                f"BCD numeric field {field.name!r} contains invalid BCD: {bcd}"
            )

        decimal_places = self._decimal_places(meta)
        value = self._format_decimal(bcd, decimal_places)
        if negative:
            value = "-" + value

        result: dict[str, Any] = {
            "raw": bytes(raw).hex().upper(),
            "bcd": bcd,
            "value": value,
        }
        unit = meta.get("unit")
        if unit:
            result["unit"] = unit
        return result

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        type_name = field.params.get("type_name", "")
        meta = dict(BCD_NUMERIC_TYPES.get(type_name, {}))
        meta.update(field.params)

        length = field.length or meta.get("length", 4)
        expected_digits = length * 2

        if isinstance(value, dict):
            if "raw" in value:
                writer.write(bytes.fromhex(str(value["raw"])))
                return
            if "value" in value:
                value = value["value"]

        text = str(value).strip()
        negative = text.startswith("-")
        if negative and not meta.get("signed"):
            raise ValueError(f"Field {field.name!r} does not support negative BCD")
        if negative:
            text = text[1:].lstrip()

        decimal_places = self._decimal_places(meta)
        if "." in text:
            integer, fraction = text.split(".", 1)
            digits = integer + fraction.ljust(decimal_places, "0")[:decimal_places]
        else:
            digits = text + ("0" * decimal_places)

        digits = "".join(ch for ch in digits if ch.isdigit())
        if len(digits) > expected_digits:
            raise ValueError(f"BCD numeric value too wide for {field.name!r}: {value}")

        raw = bytearray(
            bytes(
                (int(digits[i], 16) << 4) | int(digits[i + 1], 16)
                for i in range(0, len(digits.zfill(expected_digits)), 2)
            )
        )
        if negative:
            raw[0] |= 0x80
        writer.write(bytes(raw))

    @staticmethod
    def _decimal_places(meta: dict[str, Any]) -> int:
        fmt = str(meta.get("format", ""))
        if "." in fmt:
            return len(fmt.split(".", 1)[1])
        return 0

    @staticmethod
    def _format_decimal(digits: str, decimal_places: int) -> str:
        if decimal_places <= 0:
            return digits
        if len(digits) > decimal_places:
            integer_part = digits[:-decimal_places] or "0"
            decimal_part = digits[-decimal_places:]
            return f"{integer_part}.{decimal_part}"
        return f"0.{digits.zfill(decimal_places)}"


class _FakeReader:
    """Minimal reader for internal BCD decode calls."""
    __slots__ = ("data", "offset")
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0
    def read(self, n: int) -> bytes:
        chunk = self.data[self.offset : self.offset + n]
        self.offset += n
        return chunk
