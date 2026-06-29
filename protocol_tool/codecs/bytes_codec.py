"""Raw byte codecs — hex, bytes, ascii."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class HexCodec(FieldCodec):
    """Decodes raw bytes into an uppercase hex string.

    Parameters (from FieldNode.params):
        length: byte length (required)
        separator: character between hex bytes (default " ")
        byte_order: default ``little``; ``big`` / ``big_endian`` keep wire order
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> str:
        length = self.field_length(field, context)
        if length is None:
            raise ValueError(f"Hex field {field.name!r} requires explicit length")
        raw = reader.read(length)
        # Byte order: reverse to logical order if little-endian
        bo = field.params.get("byte_order", "little")
        if bo not in ("big", "big_endian"):
            raw = raw[::-1]
        sep = field.params.get("separator", " ")
        return raw.hex(sep).upper()

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        raw = self._to_bytes(value)
        bo = field.params.get("byte_order", "little")
        if bo not in ("big", "big_endian"):
            raw = raw[::-1]
        writer.write(raw)

    @staticmethod
    def _to_bytes(value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, dict) and "raw" in value:
            return bytes.fromhex(str(value["raw"]))
        if isinstance(value, str):
            return bytes.fromhex(value.replace(" ", ""))
        raise ValueError(f"Cannot convert {type(value).__name__} to bytes: {value!r}")


class BytesCodec(FieldCodec):
    """Decodes raw bytes as-is (returns bytes).

    Parameters (from FieldNode.params):
        length: byte length (required, or length_from)
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> bytes:
        length = self.field_length(field, context)
        if length is None:
            length = reader.remaining()
        return reader.read(length)

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        raw = HexCodec._to_bytes(value)
        writer.write(raw)


class AsciiCodec(FieldCodec):
    """Decodes bytes as ASCII text.

    Parameters (from FieldNode.params):
        length: byte length (required)
        byte_order: default ``little`` (reverse on wire); ``big`` keeps native order
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> str:
        length = self.field_length(field, context)
        if length is None:
            raise ValueError(f"ASCII field {field.name!r} requires explicit length")
        raw = reader.read(length)
        bo = field.params.get("byte_order", "little")
        if bo not in ("big", "big_endian"):
            raw = raw[::-1]
        return raw.decode("ascii", errors="replace")

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        length = self.field_length(field, context)
        text = str(value)
        raw = text.encode("ascii", errors="replace")
        if length is not None:
            if len(raw) > length:
                raise ValueError(
                    f"ASCII value too long for field {field.name!r}: "
                    f"{len(raw)} bytes, max {length}"
                )
            raw = raw.ljust(length, b"\x00")
        bo = field.params.get("byte_order", "little")
        if bo not in ("big", "big_endian"):
            raw = raw[::-1]
        writer.write(raw)
