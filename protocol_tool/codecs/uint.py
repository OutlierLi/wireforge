"""Unsigned integer codec — uint8/16/24/32/48 with configurable byte order."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class UIntCodec(FieldCodec):
    """Decodes/encodes unsigned integers of configurable width and byte order.

    Parameters are drawn from FieldNode.params:
        byte_order: "little" (default) or "big"
    """

    __slots__ = ("_width", "_byte_order")

    def __init__(self, width: int, byte_order: str = "little") -> None:
        self._width = width
        self._byte_order = byte_order

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> int:
        length = self.field_length(field, context) or self._width
        raw = reader.read(length)
        # Apply wire transforms if any
        raw = self._apply_transforms_decode(field, raw)
        value = int.from_bytes(raw, self._effective_byte_order(field))
        return value

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        if not isinstance(value, int):
            value = int(value)
        byte_order = self._effective_byte_order(field)
        length = self.field_length(field, context) or self._width
        raw = value.to_bytes(length, byte_order)
        raw = self._apply_transforms_encode(field, raw)
        writer.write(raw)

    def field_length(
        self,
        field: FieldNode,
        context: DecodeContext | BuildContext,
    ) -> int:
        if field.length is not None:
            return field.length
        if field.length_from is not None:
            ref_value = context.values.get(field.length_from)
            if ref_value is not None and isinstance(ref_value, int):
                return ref_value + field.length_adjust
        return self._width

    def _effective_byte_order(self, field: FieldNode) -> str:
        order = field.params.get("byte_order", self._byte_order)
        if order in ("big", "big_endian", "network"):
            return "big"
        return "little"

    @staticmethod
    def _apply_transforms_decode(field: FieldNode, raw: bytes) -> bytes:
        for t in field.transforms:
            if t.algorithm == "reverse_bytes":
                raw = raw[::-1]
            elif t.algorithm == "add_33h":
                raw = bytes((b + 0x33) & 0xFF for b in raw)
            elif t.algorithm == "sub_33h":
                raw = bytes((b - 0x33) & 0xFF for b in raw)
        return raw

    @staticmethod
    def _apply_transforms_encode(field: FieldNode, raw: bytes) -> bytes:
        for t in reversed(field.transforms):
            if t.algorithm == "reverse_bytes":
                raw = raw[::-1]
            elif t.algorithm == "sub_33h":
                raw = bytes((b - 0x33) & 0xFF for b in raw)
            elif t.algorithm == "add_33h":
                raw = bytes((b + 0x33) & 0xFF for b in raw)
        return raw


# Import ByteWriter for type checking at runtime
from protocol_tool.codecs.base import ByteWriter  # noqa: E402
