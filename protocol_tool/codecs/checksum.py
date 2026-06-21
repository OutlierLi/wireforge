"""Checksum codec — computes/verifies checksums over accumulated raw sections.

Ported from old project's checksum_engine.py.
Supports: sum8, xor8, crc16_modbus, crc16_ccitt, crc8.
"""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


# ---------------------------------------------------------------------------
# Algorithm implementations
# ---------------------------------------------------------------------------

def _sum8(data: bytes, **_kw: Any) -> int:
    return sum(data) & 0xFF


def _xor8(data: bytes, **_kw: Any) -> int:
    result = 0
    for b in data:
        result ^= b
    return result


def _crc16_ccitt(data: bytes, *, initial: int = 0x0000, poly: int = 0x1021) -> int:
    crc = initial & 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _crc16_modbus(data: bytes, *, initial: int = 0xFFFF, poly: int = 0x8005) -> int:
    """CRC16-Modbus (reflected)."""
    crc = initial & 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc


def _crc8(data: bytes, *, poly: int = 0x07, initial: int = 0x00) -> int:
    crc = initial & 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


ALGORITHMS: dict[str, dict[str, Any]] = {
    "sum8": {
        "func": _sum8,
        "output_bytes": 1,
        "output_byte_order": None,
    },
    "xor8": {
        "func": _xor8,
        "output_bytes": 1,
        "output_byte_order": None,
    },
    "crc16_ccitt": {
        "func": _crc16_ccitt,
        "output_bytes": 2,
        "output_byte_order": "big",
    },
    "crc16_modbus": {
        "func": _crc16_modbus,
        "output_bytes": 2,
        "output_byte_order": "little",
    },
    "crc8": {
        "func": _crc8,
        "output_bytes": 1,
        "output_byte_order": None,
    },
}


def register_checksum_algorithm(
    name: str,
    func: Callable[..., int],
    output_bytes: int,
    output_byte_order: str | None = None,
) -> None:
    """Register a new checksum algorithm."""
    ALGORITHMS[name] = {
        "func": func,
        "output_bytes": output_bytes,
        "output_byte_order": output_byte_order,
    }


# ---------------------------------------------------------------------------
# ChecksumCodec
# ---------------------------------------------------------------------------

class ChecksumCodec(FieldCodec):
    """Decodes (verifies) and encodes (computes) checksums.

    Parameters (from FieldNode.params):
        algorithm: key into ALGORITHMS dict (e.g. "sum8", "crc16_modbus")
        cover: list of field names whose raw bytes are checksummed, in order.
              e.g. ["control", "user_data"]
        params: algorithm-specific parameters (initial, poly, etc.)

    On decode:
        The engine accumulates raw_sections during parsing.
        This codec looks up the cover sections, concatenates them,
        computes the checksum, compares with the wire value.
        Returns the computed value.

    On encode:
        Same computation, writes the result bytes.
    """

    def __init__(self, algorithm: str = "sum8") -> None:
        self._algorithm_name = algorithm

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> int:
        algo_name = field.params.get("algorithm", self._algorithm_name)
        algo = ALGORITHMS.get(algo_name)
        if algo is None:
            raise ValueError(
                f"Unknown checksum algorithm: {algo_name!r}. "
                f"Known: {sorted(ALGORITHMS)}"
            )

        algo_params = self._parse_params(field.params.get("params", {}))
        length = self.field_length(field, context) or algo["output_bytes"]
        wire_bytes = reader.read(length)
        wire_value = int.from_bytes(
            wire_bytes,
            algo["output_byte_order"] or "big",
        )

        # Compute expected checksum from accumulated raw sections
        cover = field.params.get("cover", [])
        expected = self._compute(algo, cover, context, algo_params)

        if expected != wire_value:
            raise ValueError(
                f"Checksum mismatch for field {field.name!r}: "
                f"expected 0x{expected:0{algo['output_bytes']*2}X}, "
                f"got 0x{wire_value:0{algo['output_bytes']*2}X}"
            )
        return wire_value

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        algo_name = field.params.get("algorithm", self._algorithm_name)
        algo = ALGORITHMS.get(algo_name)
        if algo is None:
            raise ValueError(f"Unknown checksum algorithm: {algo_name!r}")

        algo_params = self._parse_params(field.params.get("params", {}))
        cover = field.params.get("cover", [])

        computed = self._compute(algo, cover, context, algo_params)
        length = self.field_length(field, context) or algo["output_bytes"]
        order = algo["output_byte_order"] or "big"
        writer.write(computed.to_bytes(length, order))

    def field_length(
        self,
        field: FieldNode,
        context: DecodeContext | BuildContext,
    ) -> int | None:
        algo_name = field.params.get("algorithm", self._algorithm_name)
        algo = ALGORITHMS.get(algo_name)
        if algo:
            return algo["output_bytes"]
        return field.length

    @staticmethod
    def _compute(
        algo: dict[str, Any],
        cover: list[str],
        context: DecodeContext | BuildContext,
        params: dict[str, Any],
    ) -> int:
        parts: list[bytes] = []
        for name in cover:
            part = context.raw_sections.get(name)
            if part is not None:
                parts.append(part)
        data = b"".join(parts)
        return algo["func"](data, **params)

    @staticmethod
    def _parse_params(raw: dict[str, Any]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, val in raw.items():
            if isinstance(val, str) and val.lower().startswith("0x"):
                parsed[key] = int(val, 16)
            else:
                parsed[key] = val
        return parsed
