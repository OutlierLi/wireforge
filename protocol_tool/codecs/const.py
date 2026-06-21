"""Const codecs — fixed-value fields that validate on decode, emit on build."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class ConstCodec(FieldCodec):
    """A field with a fixed expected value.

    On decode: read length bytes, assert they match the expected value.
    On encode: write the expected value.

    Parameters (from FieldNode.params):
        value: the expected byte value (int or hex string like "68" or "0x68")
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> int:
        expected = self._resolve_value(field)
        length = self.field_length(field, context) or 1
        raw = reader.read(length)
        actual = raw[0] if length == 1 else int.from_bytes(raw, "big")
        if actual != expected:
            raise ValueError(
                f"Const field {field.name!r}: expected 0x{expected:02X}, "
                f"got 0x{actual:02X}"
            )
        return expected

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        # Always use the field's configured value, ignoring user input
        expected = self._resolve_value(field)
        length = self.field_length(field, context) or 1
        writer.write(expected.to_bytes(length, "big"))

    def field_length(
        self,
        field: FieldNode,
        context: DecodeContext | BuildContext,
    ) -> int:
        if field.length is not None:
            return field.length
        val = field.params.get("value", 0)
        if isinstance(val, int):
            return max(1, (val.bit_length() + 7) // 8)
        return 1

    @staticmethod
    def _resolve_value(field: FieldNode) -> int:
        val = field.params.get("value", 0)
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            text = val.strip().upper().replace("0X", "")
            return int(text, 16)
        return int(val)


class ConstRepeatCodec(FieldCodec):
    """A repeatable constant byte (e.g. 0xFE preamble).

    On decode: consume 0 or more repetitions of the expected byte.
    On encode: write exactly the specified count of the expected byte.

    Parameters (from FieldNode.params):
        value: the expected byte value (int or hex string)
        min: minimum repetitions (default 0)
        max: maximum repetitions (default unlimited)
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> list[int]:
        expected = ConstCodec._resolve_value(field)
        min_count = field.params.get("min", 0)
        max_count = field.params.get("max", 255)

        values: list[int] = []
        while len(values) < max_count and not reader.exhausted():
            b = reader.peek(1)[0]
            if b == expected:
                reader.read(1)
                values.append(b)
            else:
                break

        if len(values) < min_count:
            raise ValueError(
                f"ConstRepeat field {field.name!r}: expected at least {min_count} "
                f"occurrences of 0x{expected:02X}, got {len(values)}"
            )
        return values

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        expected = ConstCodec._resolve_value(field)
        if value is None or value == 0:
            count = field.params.get("min", 0)
        elif isinstance(value, int):
            count = value
        elif isinstance(value, (list, tuple)):
            count = len(value)
        else:
            count = field.params.get("min", 0)
        writer.write(bytes([expected]) * count)

    def field_length(
        self,
        field: FieldNode,
        context: DecodeContext | BuildContext,
    ) -> int | None:
        # Variable length — cannot determine without reading
        return None
