"""Wire-level byte transforms.

Transforms are applied before decode (wire → logical) and after encode
(logical → wire). They are referenced by name in FieldNode.transforms.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    pass


class ReverseBytesTransform(FieldCodec):
    """Reverses byte order in-place.

    Used as a wire transform (not a standalone codec).
    Type ref: "reverse_bytes"
    """

    def decode(self, field, reader, context):
        raise NotImplementedError("ReverseBytesTransform is a wire transform, not a field codec")

    def encode(self, field, value, writer, context):
        raise NotImplementedError("ReverseBytesTransform is a wire transform, not a field codec")


class Add33HTransform(FieldCodec):
    """Adds 0x33 to each byte (mod 256).

    Used for DLT645 data domain encoding.
    Type ref: "add_33h"
    """

    def decode(self, field, reader, context):
        raise NotImplementedError("Add33HTransform is a wire transform, not a field codec")

    def encode(self, field, value, writer, context):
        raise NotImplementedError("Add33HTransform is a wire transform, not a field codec")


class Sub33HTransform(FieldCodec):
    """Subtracts 0x33 from each byte (mod 256).

    Used for DLT645 data domain decoding.
    Type ref: "sub_33h"
    """

    def decode(self, field, reader, context):
        raise NotImplementedError("Sub33HTransform is a wire transform, not a field codec")

    def encode(self, field, value, writer, context):
        raise NotImplementedError("Sub33HTransform is a wire transform, not a field codec")


# ---------------------------------------------------------------------------
# Transform application helpers (used by other codecs)
# ---------------------------------------------------------------------------

def apply_transforms_decode(raw: bytes, transforms: tuple) -> bytes:
    """Apply wire→logical transforms in order.

    Each transform is a TransformSpec with algorithm name and params.
    """
    for t in transforms:
        if t.algorithm == "reverse_bytes":
            width = t.params.get("width", 0)
            if width and width > 1:
                # Reverse in width-sized chunks
                chunks = [raw[i:i+width][::-1] for i in range(0, len(raw), width)]
                raw = b"".join(chunks)
            else:
                raw = raw[::-1]
        elif t.algorithm == "add_33h":
            raw = bytes((b + 0x33) & 0xFF for b in raw)
        elif t.algorithm == "sub_33h":
            raw = bytes((b - 0x33) & 0xFF for b in raw)
        elif t.algorithm == "pn_fn":
            raw = bytes(
                (0xAA if (b & 0x10) else 0) ^ (b & 0x0F) | (b & 0xF0)
                for b in raw
            )
    return raw


def apply_transforms_encode(raw: bytes, transforms: tuple) -> bytes:
    """Apply logical→wire transforms in reverse order.

    Encode is the INVERSE of decode:
    - decode sub_33h (wire→logical: subtract 0x33) → encode add_33h (logical→wire: add 0x33)
    - decode add_33h (wire→logical: add 0x33)     → encode sub_33h (logical→wire: subtract 0x33)
    """
    for t in reversed(transforms):
        if t.algorithm == "reverse_bytes":
            width = t.params.get("width", 0)
            if width and width > 1:
                chunks = [raw[i:i+width][::-1] for i in range(0, len(raw), width)]
                raw = b"".join(chunks)
            else:
                raw = raw[::-1]
        elif t.algorithm == "sub_33h":
            # decode subtracts 0x33 → encode ADDS 0x33
            raw = bytes((b + 0x33) & 0xFF for b in raw)
        elif t.algorithm == "add_33h":
            # decode adds 0x33 → encode SUBTRACTS 0x33
            raw = bytes((b - 0x33) & 0xFF for b in raw)
        elif t.algorithm == "pn_fn":
            raw = bytes(
                (0xAA if (b & 0x10) else 0) ^ (b & 0x0F) | (b & 0xF0)
                for b in raw
            )
    return raw
