"""Codec registry — decoupled from protocol definitions.

The registry maps type_ref strings to FieldCodec instances.
Protocol IR only references codec names; the runtime resolves them here.

New codecs can be registered at any time before decode/build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.codecs.base import FieldCodec


class CodecRegistry:
    """Singleton registry mapping codec names to FieldCodec instances."""

    def __init__(self) -> None:
        self._codecs: dict[str, FieldCodec] = {}

    def register(self, name: str, codec: FieldCodec) -> None:
        """Register a codec by name. Overwrites if name already exists."""
        self._codecs[name] = codec

    def get(self, name: str) -> FieldCodec:
        """Get a codec by name.

        Raises KeyError if not found.
        """
        if name not in self._codecs:
            raise KeyError(
                f"Unknown codec: {name!r}. Known: {sorted(self._codecs.keys())}"
            )
        return self._codecs[name]

    def has(self, name: str) -> bool:
        """Check if a codec name is registered."""
        return name in self._codecs

    def known_names(self) -> set[str]:
        """Return all registered codec names."""
        return set(self._codecs.keys())

    # -- Convenience for registering many at once --

    def register_all(self, mapping: dict[str, FieldCodec]) -> None:
        """Register multiple codecs at once."""
        for name, codec in mapping.items():
            self.register(name, codec)


# ---------------------------------------------------------------------------
# Built-in codecs factory
# ---------------------------------------------------------------------------

def create_builtin_registry() -> CodecRegistry:
    """Create a CodecRegistry pre-populated with all built-in codecs.

    This is the recommended way to get a ready-to-use registry.
    Imported lazily to avoid circular imports.
    """
    from protocol_tool.codecs.uint import (
        UIntCodec,
    )
    from protocol_tool.codecs.bcd import (
        BcdCodec,
        BcdNumericCodec,
    )
    from protocol_tool.codecs.bitset import BitSetCodec
    from protocol_tool.codecs.const import ConstCodec, ConstRepeatCodec
    from protocol_tool.codecs.bytes_codec import (
        HexCodec,
        BytesCodec,
        AsciiCodec,
    )
    from protocol_tool.codecs.checksum import ChecksumCodec
    from protocol_tool.codecs.transforms import (
        ReverseBytesTransform,
        Add33HTransform,
        Sub33HTransform,
    )
    from protocol_tool.codecs.struct_codec import StructCodec
    from protocol_tool.codecs.array_codec import ArrayCodec
    from protocol_tool.codecs.enum_codec import EnumCodec
    from protocol_tool.codecs.routed import RoutedPayloadCodec

    registry = CodecRegistry()

    # Unsigned integers
    registry.register("uint8", UIntCodec(1, "little"))
    registry.register("uint16_le", UIntCodec(2, "little"))
    registry.register("uint16_be", UIntCodec(2, "big"))
    registry.register("uint24_le", UIntCodec(3, "little"))
    registry.register("uint24_be", UIntCodec(3, "big"))
    registry.register("uint32_le", UIntCodec(4, "little"))
    registry.register("uint32_be", UIntCodec(4, "big"))
    registry.register("uint48_le", UIntCodec(6, "little"))
    registry.register("uint48_be", UIntCodec(6, "big"))

    # BCD
    registry.register("bcd", BcdCodec())
    registry.register("bcd_numeric", BcdNumericCodec())

    # Bitfield
    registry.register("bitset", BitSetCodec())

    # Constants
    registry.register("const", ConstCodec())
    registry.register("const_repeat", ConstRepeatCodec())

    # Raw bytes
    registry.register("hex", HexCodec())
    registry.register("bytes", BytesCodec())
    registry.register("ascii", AsciiCodec())

    # Composite
    registry.register("struct", StructCodec())
    registry.register("array", ArrayCodec())
    registry.register("enum", EnumCodec())

    # Checksums
    registry.register("sum8", ChecksumCodec("sum8"))
    registry.register("xor8", ChecksumCodec("xor8"))
    registry.register("crc16_modbus", ChecksumCodec("crc16_modbus"))
    registry.register("crc16_ccitt", ChecksumCodec("crc16_ccitt"))
    registry.register("crc8", ChecksumCodec("crc8"))

    # Routed payload (must be set up after engine creation — see RoutedPayloadCodec)
    registry.register("routed_payload", RoutedPayloadCodec())

    # Wire transforms (not codecs, but registered for lookup)
    registry.register("reverse_bytes", ReverseBytesTransform())
    registry.register("add_33h", Add33HTransform())
    registry.register("sub_33h", Sub33HTransform())

    return registry
