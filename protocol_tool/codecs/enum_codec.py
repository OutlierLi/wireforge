"""Enum codec — decodes integer values to named constants."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


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

        values = field.params.get("values", {})
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

        if isinstance(value, dict):
            if "raw" in value:
                raw_int = int(value["raw"])
            elif "label" in value:
                # Reverse lookup
                values = field.params.get("values", {})
                raw_int = next(
                    (k for k, v in values.items() if v == value["label"]),
                    0,
                )
            else:
                raw_int = 0
        elif isinstance(value, str):
            values = field.params.get("values", {})
            raw_int = next(
                (k for k, v in values.items() if v == value),
                0,
            )
        else:
            raw_int = int(value)

        writer.write(raw_int.to_bytes(length, "big"))
