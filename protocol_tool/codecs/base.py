"""Field codec abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class ByteWriter:
    """Accumulates bytes during encoding.

    Ported from old project's fields.py ByteWriter.
    """

    __slots__ = ("_chunks",)

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def write(self, data: bytes) -> None:
        self._chunks.append(data)

    def bytes(self) -> bytes:
        return b"".join(self._chunks)

    def __len__(self) -> int:
        return sum(len(c) for c in self._chunks)


class FieldCodec(ABC):
    """Abstract base for all field codecs.

    Each concrete codec handles one type_ref (e.g. "uint8", "bcd", "bitset").
    Codecs are stateless — all parameters come from the FieldNode.

    Lifecycle:
        decode:  raw bytes → decoded value  (reader advances)
        encode:  python value → bytes       (writer accumulates)
    """

    @abstractmethod
    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> Any:
        """Read bytes from reader, return decoded Python value.

        The reader's position MUST advance by exactly the number of bytes consumed.
        """
        ...

    @abstractmethod
    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        """Encode a Python value and write bytes to writer."""
        ...

    def field_length(
        self,
        field: FieldNode,
        context: DecodeContext | BuildContext,
    ) -> int | None:
        """Return the length in bytes this field will consume/produce.

        Returns None if the length is dynamic and not yet known.
        """
        # Check explicit length
        if field.length is not None:
            return field.length
        # Check length_from reference
        if field.length_from is not None:
            ref_value = context.values.get(field.length_from)
            if ref_value is not None and isinstance(ref_value, int):
                return ref_value + field.length_adjust
        return None
