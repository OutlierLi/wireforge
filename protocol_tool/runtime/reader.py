"""DecodeReader — byte buffer with position tracking during decode.

Ported from old project's fields.py ByteReader, with boundary support added.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DecodeReader:
    """Reads bytes sequentially from a buffer, tracking position and boundary.

    Parameters
    ----------
    data:
        The complete byte buffer to read from.
    offset:
        Current read position (defaults to 0, start of buffer).
    boundary:
        Maximum allowed read position. Reads beyond this raise BufferOverrunError.
        Defaults to len(data).
    """

    data: bytes
    offset: int = 0
    boundary: int | None = None

    def __post_init__(self) -> None:
        if self.boundary is None:
            self.boundary = len(self.data)

    # -- Read operations --

    def read(self, n: int) -> bytes:
        """Read exactly n bytes and advance offset.

        Raises BufferOverrunError if not enough bytes remain within boundary.
        """
        if n < 0:
            raise ValueError(f"Cannot read negative bytes: {n}")
        if n == 0:
            return b""
        end = self.offset + n
        if end > self.boundary:
            raise BufferOverrunError(
                f"Attempted to read {n} bytes at offset {self.offset}, "
                f"but only {self.boundary - self.offset} remain within boundary"
            )
        result = self.data[self.offset : end]
        self.offset = end
        return result

    def read_remaining(self) -> bytes:
        """Read all remaining bytes up to the boundary."""
        return self.read(self.remaining())

    def peek(self, n: int) -> bytes:
        """Read n bytes without advancing offset."""
        end = self.offset + n
        if end > self.boundary:
            raise BufferOverrunError(
                f"Attempted to peek {n} bytes at offset {self.offset}"
            )
        return self.data[self.offset : end]

    # -- State queries --

    def remaining(self) -> int:
        """Number of bytes still readable within boundary."""
        return self.boundary - self.offset

    def exhausted(self) -> bool:
        """True if no bytes remain within boundary."""
        return self.offset >= self.boundary

    def tell(self) -> int:
        """Current read position."""
        return self.offset

    # -- Position management --

    def slice(self, length: int) -> tuple[bytes, int, int]:
        """Read length bytes, return (bytes, start_offset, end_offset).

        Useful for checksum computation — the caller gets both the bytes
        and the position range they came from.
        """
        start = self.offset
        data = self.read(length)
        return data, start, self.offset

    def fork(self) -> DecodeReader:
        """Create an independent reader at the current position.

        The forked reader shares the same underlying data buffer but has
        its own offset. Useful for speculative/trial parsing.
        """
        return DecodeReader(
            data=self.data,
            offset=self.offset,
            boundary=self.boundary,
        )


class BufferOverrunError(ValueError):
    """Raised when attempting to read past the buffer boundary."""
    pass
