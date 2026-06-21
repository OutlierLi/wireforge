"""Hex string normalization utilities."""

import re


def normalize_hex(text: str) -> str:
    """Normalize a hex string: remove whitespace, spaces, newlines, 0x prefixes.

    >>> normalize_hex("68 10 00 00 00 00 00 68 11 04 33 33 34 33 C5 16")
    '6810000000000068110433333433C516'
    """
    text = text.strip()
    # Remove "0x" or "0X" prefixes
    text = re.sub(r"0[xX]", "", text)
    # Remove all non-hex characters
    text = re.sub(r"[^0-9A-Fa-f]", "", text)
    return text.upper()


def hex_to_bytes(text: str) -> bytes:
    """Convert a hex string to bytes."""
    return bytes.fromhex(normalize_hex(text))


def bytes_to_hex(data: bytes, separator: str = " ") -> str:
    """Convert bytes to a hex string."""
    return data.hex(separator).upper()


def format_hex_table(data: bytes, bytes_per_line: int = 16) -> str:
    """Format bytes as a hex table with offset, hex, and ASCII columns."""
    lines = []
    for i in range(0, len(data), bytes_per_line):
        chunk = data[i : i + bytes_per_line]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04X}  {hex_part:<{bytes_per_line * 3}}  {ascii_part}")
    return "\n".join(lines)
