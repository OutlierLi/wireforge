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

    # Try DLT645 preamble first
    preamble_idx = data.find(b"\x68")
    if preamble_idx < 0:
        # No start byte found, skip to end
        return None, data

    # Skip anything before the 68
    if preamble_idx > 0 and preamble_idx < 4:
        # Partial preamble, skip to 68
        data = data[preamble_idx:]

    start_idx = data.find(b"\x68")
    if start_idx < 0:
        return None, data

    # Discard garbage before frame start
    if start_idx > 0:
        # Check if there are FE bytes (DLT645 preamble)
        garbage = data[:start_idx]
        if not all(b == 0xFE for b in garbage):
            # Non-preamble garbage, discard it
            data = data[start_idx:]
            start_idx = 0

    # Now data starts with 68 (possibly preceded by FE preamble)
    # Find the actual 68 position
    pos_68 = data.find(b"\x68")
    if pos_68 < 0:
        return None, data
    if pos_68 > 0:
        # Preamble before 68
        if not all(b == 0xFE for b in data[:pos_68]):
            data = data[pos_68:]
            pos_68 = 0
        else:
            # Include preamble in frame
            pass

    frame_start = pos_68 if all(b == 0xFE for b in data[:pos_68]) else pos_68
    # Actually simpler: just use 68 position
    idx_68 = data.find(b"\x68")
    if idx_68 < 0:
        return None, data

    # Include any FE preamble bytes before 68
    preamble = b""
    if idx_68 > 0:
        preamble = data[:idx_68]
        if not all(b == 0xFE for b in preamble):
            # Not preamble, discard
            return None, data[idx_68:]
        data = data[idx_68:]  # strip preamble for length calculation

    # Need at least 68 + 2 bytes length
    if len(data) < 3:
        return None, preamble + data if preamble else data

    # CSG frame: length is uint16 LE at offset 1 from 68
    total_len = int.from_bytes(data[1:3], "little")
    if total_len < 6:
        # Invalid length, skip this 68
        return None, data[1:]

    if len(data) < total_len:
        # Incomplete frame
        return None, preamble + data if preamble else data

    # Check end byte
    if data[total_len - 1] != 0x16:
        # CSG frame must end with 16
        # Could be DLT645 with 16 at end
        # Try again by skipping this invalid frame
        return None, data[1:]

    frame = preamble + data[:total_len]
    return frame, data[total_len:]
