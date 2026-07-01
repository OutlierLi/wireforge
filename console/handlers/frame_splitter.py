"""Frame splitter — split raw serial bytes into complete protocol frames.

Handles CSG (68 + length) and DLT645 (FE preamble + 68).
"""

from __future__ import annotations


def split_frames(data: bytes) -> tuple[list[bytes], bytes]:
    """Split raw bytes into complete frames, returning (frames, remainder).

    CSG frames: 68 + 2-byte-LE-length + ... + 16  (length includes 68 and 16)
    DLT645 frames: FE FE FE FE + 68 + ... + 16
    """
    frames: list[bytes] = []
    while True:
        frame, data = _extract_one_frame(data)
        if frame:
            frames.append(frame)
        else:
            break
    return frames, data


def _extract_one_frame(data: bytes) -> tuple[bytes | None, bytes]:
    """Extract one complete frame from the beginning of data.

    Returns (frame, remaining_data) or (None, original_data) if incomplete.
    """
    if len(data) < 6:
        return None, data

    preamble, body = _split_fe_preamble(data)
    if not body or body[0] != 0x68:
        # No start byte found, skip one byte and retry later
        if len(data) > 1:
            return None, data[1:]
        return None, data

    # DLT645: 68 + addr(6) + 68 + ctrl + len + data + cs + 16
    if len(body) >= 10 and body[7] == 0x68:
        data_len = body[9]
        frame_len = 12 + data_len
        if len(body) < frame_len:
            return None, data
        if body[frame_len - 1] != 0x16:
            return None, data[1:]
        frame = preamble + body[:frame_len]
        return frame, body[frame_len:]

    # CSG: 68 + uint16_le total length (includes start and end)
    if len(body) < 3:
        return None, data

    total_len = int.from_bytes(body[1:3], "little")
    if total_len < 6:
        return None, data[1:]

    if len(body) < total_len:
        return None, data

    if body[total_len - 1] != 0x16:
        return None, data[1:]

    frame = preamble + body[:total_len]
    return frame, body[total_len:]


def _split_fe_preamble(data: bytes) -> tuple[bytes, bytes]:
    """Strip leading 0xFE preamble; return (preamble, rest)."""
    idx = 0
    while idx < len(data) and data[idx] == 0xFE:
        idx += 1
    return data[:idx], data[idx:]
