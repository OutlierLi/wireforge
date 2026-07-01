"""Array codec — repeated items driven by count_ref or until boundary."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class ArrayCodec(FieldCodec):
    """Decodes/encodes a repeated sequence of homogeneous items.

    Parameters (from FieldNode.params):
        item_type: type_ref of each item (e.g. "bcd", "uint8")
        item_params: params for each item
        count_ref: field name whose value gives the count
        count: fixed count (alternative to count_ref)
        item_name: base name for items ("item" → "item[0]", "item[1]", ...)
    """

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> list[Any]:
        from protocol_tool.codecs import CodecRegistry
        from protocol_tool.ir.nodes import FieldNode as FN

        count = self._resolve_count(field, context)
        item_type = field.params.get("item_type", "hex")
        item_params = field.params.get("item_params", {})
        item_name = field.params.get("item_name", "item")
        item_length = item_params.get("length")
        if item_type == "ascii" and item_length is None:
            item_length = 1
        item_length_from = item_params.get("length_from")
        results: list[Any] = []
        for i in range(count) if count is not None else _forever():
            if count is None and reader.exhausted():
                break

            item_field = FN(
                id=f"{field.id}[{i}]",
                name=f"{item_name}[{i}]",
                type_ref=item_type,
                params={k: v for k, v in item_params.items() if k not in ("length", "length_from")},
                length=item_length,
                length_from=item_length_from,
            )
            codec = _get_codec(item_type)
            value = codec.decode(item_field, reader, context)
            results.append(value)

            if count is not None and len(results) >= count:
                break

        return results

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        from protocol_tool.ir.nodes import FieldNode as FN

        item_type = field.params.get("item_type", "hex")
        item_params = field.params.get("item_params", {})
        item_name = field.params.get("item_name", "item")
        item_length = item_params.get("length")
        if item_type == "ascii" and item_length is None:
            item_length = 1
        item_length_from = item_params.get("length_from")

        if isinstance(value, str) and not isinstance(value, (list, tuple)):
            count = self._resolve_count(field, context) or field.length
            items = list(value[:count].ljust(count, "\x00")) if count else [value]
        else:
            items = list(value) if isinstance(value, (list, tuple)) else [value]

        for i, item_value in enumerate(items):
            item_field = FN(
                id=f"{field.id}[{i}]",
                name=f"{item_name}[{i}]",
                type_ref=item_type,
                params={k: v for k, v in item_params.items() if k not in ("length", "length_from")},
                length=item_length,
                length_from=item_length_from,
            )
            codec = _get_codec(item_type)
            codec.encode(item_field, item_value, writer, context)

    @staticmethod
    def _resolve_count(field: FieldNode, context: DecodeContext | BuildContext) -> int | None:
        count_ref = field.params.get("count_ref")
        if count_ref is not None:
            val = context.get(count_ref)
            if val is not None:
                return int(val)
        count = field.params.get("count")
        if count is not None:
            return int(count)
        if field.length is not None:
            return int(field.length)
        return None


def _get_codec(type_ref: str):
    from protocol_tool.codecs import create_builtin_registry
    if not hasattr(_get_codec, "_registry"):
        _get_codec._registry = create_builtin_registry()
    return _get_codec._registry.get(type_ref)


def _forever():
    """Infinite iterator."""
    i = 0
    while True:
        yield i
        i += 1
