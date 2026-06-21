"""BitSet codec — decodes/encodes bit-packed fields within a byte."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class BitSetCodec(FieldCodec):
    """Decodes a fixed-length byte sequence into named bit fields.

    Parameters (from FieldNode.params):
        bits: list of {"name": str, "offset": int, "width": int}
            or list of {"name": str, "bit": int} for single bits.

    Decoded value is a dict with:
        - each named bit field as a key
        - "raw": the raw integer value of the full byte(s)

    Example:
        params = {
            "bits": [
                {"name": "func", "offset": 0, "width": 5},
                {"name": "follow", "offset": 5, "width": 1},
                {"name": "ack", "offset": 6, "width": 1},
                {"name": "dir", "offset": 7, "width": 1},
            ]
        }
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

        bits = field.params.get("bits", [])
        result: dict[str, Any] = {"raw": raw_int}

        for spec in bits:
            name = spec["name"]
            if "bit" in spec:
                result[name] = (raw_int >> spec["bit"]) & 1
            elif "offset" in spec and "width" in spec:
                mask = (1 << spec["width"]) - 1
                result[name] = (raw_int >> spec["offset"]) & mask
            elif "bits" in spec:
                # Multi-bit field from individual bit positions
                parsed = 0
                for bit in spec["bits"]:
                    parsed = (parsed << 1) | ((raw_int >> bit) & 1)
                result[name] = parsed

        return result

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        length = self.field_length(field, context) or 1
        bits = field.params.get("bits", [])

        if isinstance(value, int):
            raw_int = value
        elif isinstance(value, dict):
            if "raw" in value:
                raw_int = int(value["raw"])
            else:
                raw_int = 0
                for spec in bits:
                    name = spec["name"]
                    val = int(value.get(name, spec.get("default", 0)))
                    if "bit" in spec:
                        raw_int |= (val & 1) << spec["bit"]
                    elif "offset" in spec and "width" in spec:
                        mask = (1 << spec["width"]) - 1
                        raw_int |= (val & mask) << spec["offset"]
                    elif "bits" in spec:
                        for i, bit in enumerate(reversed(spec["bits"])):
                            raw_int |= ((val >> i) & 1) << bit
        else:
            raw_int = int(value)

        writer.write(raw_int.to_bytes(length, "big"))
