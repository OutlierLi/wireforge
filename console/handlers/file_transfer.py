"""CSG AFN=07 file transfer helpers — segmentation, CRC, path normalization, ACK parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protocol_tool.codecs.checksum import _crc16_ccitt

from console.arg_utils import strip_nested_quotes

ALLOWED_SEGMENT_SIZES = frozenset({128, 256, 512, 1024})
CACHE_VERSION = 2
CACHE_CRC_ALGO = "ccitt"

ERROR_CODE_MESSAGES = {
    "00": "通信超时",
    "01": "无效数据标识内容",
    "02": "长度错误",
    "03": "校验错误",
    "04": "数据标识编码不存在",
    "05": "格式错误",
    "06": "表号重复",
    "07": "表号不存在",
    "08": "电表应用层无应答",
    "09": "主节点忙",
    "0A": "主节点不支持此命令",
    "0B": "从节点不应答",
    "0C": "从节点不在网内",
    "0D": "添加任务时剩余可分配任务数不足",
    "0E": "上报任务数据时任务不存在",
    "0F": "任务 ID 重复",
    "10": "查询任务时模块没有此任务",
    "11": "任务 ID 不存在",
    "FF": "其他错误",
}


class FileTransferError(RuntimeError):
    """Raised when file-transfer workflow receives invalid input or response."""


@dataclass(frozen=True, slots=True)
class FileSegment:
    number: int
    data: bytes
    crc16: int

    @property
    def length(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class SegmentedFile:
    path: Path
    data: bytes
    size: int
    crc16: int
    segment_size: int
    segments: tuple[FileSegment, ...]

    @property
    def total_segments(self) -> int:
        return len(self.segments)


@dataclass(frozen=True, slots=True)
class AckResult:
    ok: bool
    wait_time: int = 0
    error_code: int | None = None
    error_message: str | None = None


def crc16_ccitt(data: bytes) -> int:
    return _crc16_ccitt(data)


def segment_file(path: str | Path, segment_size: int) -> SegmentedFile:
    source = Path(path)
    if not source.exists():
        raise FileTransferError(f"bin file not found: {source}")
    if not source.is_file():
        raise FileTransferError(f"bin path is not a file: {source}")
    if segment_size not in ALLOWED_SEGMENT_SIZES:
        raise FileTransferError("segment-size must be 128/256/512/1024")

    data = source.read_bytes()
    chunks = _chunks(data, segment_size)
    segments = tuple(
        FileSegment(index, chunk, crc16_ccitt(chunk))
        for index, chunk in enumerate(chunks)
    )
    return SegmentedFile(
        path=source,
        data=data,
        size=len(data),
        crc16=crc16_ccitt(data),
        segment_size=segment_size,
        segments=segments,
    )


def normalize_file_path(raw: str, *, root: Path | None = None) -> Path:
    """Resolve firmware path with nested quote stripping and common search locations."""
    cleaned = strip_nested_quotes(str(raw))
    if not cleaned:
        raise FileTransferError("empty file path")

    project_root = (root or Path(__file__).resolve().parent.parent.parent).resolve()
    source = Path(cleaned)
    candidates: list[Path] = []

    if source.is_absolute():
        candidates.append(source)
    else:
        candidates.extend([
            source,
            Path.cwd() / source,
            project_root / source,
            project_root / "database" / "bin" / source,
            project_root / "database" / "bin" / source.name,
        ])

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved

    return candidates[0].resolve()


def parse_duration(text: str | int | float) -> float:
    if isinstance(text, (int, float)):
        return float(text)
    raw = str(text).strip().lower()
    if not raw:
        raise FileTransferError("empty duration")
    if raw.endswith("ms"):
        return float(raw[:-2]) / 1000.0
    if raw.endswith("s"):
        return float(raw[:-1])
    return float(raw)


def parsed_di(decoded: dict[str, Any]) -> str:
    values = decoded.get("values", {}) if isinstance(decoded.get("values"), dict) else {}
    di = _find_decoded_value(values, "di")
    if di is None:
        return ""
    return "".join(str(di).replace("0x", "").replace("0X", "").split()).upper()


def payload_from_decoded(decoded: dict[str, Any]) -> dict[str, Any]:
    values = decoded.get("values", {}) if isinstance(decoded.get("values"), dict) else {}
    for container_name in ("data_content", "user_data"):
        container = values.get(container_name)
        if not isinstance(container, dict):
            continue
        payload = container.get("di_payload")
        if isinstance(payload, dict):
            return payload
        nested = _find_di_payload(container)
        if nested:
            return nested
    return {}


def _find_di_payload(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        payload = node.get("di_payload")
        if isinstance(payload, dict):
            return payload
        for value in node.values():
            nested = _find_di_payload(value)
            if nested:
                return nested
    return {}


def ack_from_decoded(decoded: dict[str, Any]) -> AckResult:
    values = decoded.get("values", {}) if isinstance(decoded.get("values"), dict) else {}
    path = str(decoded.get("path") or "")
    payload = payload_from_decoded(decoded)
    di = parsed_di(decoded)

    if "afn00_ack" in path or di == "E8010001" or (
        isinstance(payload, dict) and "wait_time" in payload and "error_code" not in payload
    ):
        wait_time = payload.get("wait_time") if isinstance(payload, dict) else _find_decoded_value(values, "wait_time")
        return AckResult(ok=True, wait_time=int(wait_time or 0))

    if "afn00_nak" in path or di == "E8010002" or (
        isinstance(payload, dict) and "error_code" in payload
    ):
        error = payload.get("error_code") if isinstance(payload, dict) else _find_decoded_value(values, "error_code")
        code = ""
        if isinstance(error, dict):
            code = str(error.get("code", "")).upper()
            meaning = error.get("meaning")
        elif error is not None:
            if isinstance(error, int):
                code = f"{error:02X}"
            else:
                code = str(error).replace("0x", "").replace("0X", "").upper()
            meaning = None
        else:
            meaning = None
        message = str(meaning or ERROR_CODE_MESSAGES.get(code, f"未知错误({code or '?'})"))
        err_int = int(code, 16) if code else None
        return AckResult(ok=False, error_code=err_int, error_message=message)

    raise FileTransferError(f"not ACK/NAK frame: DI={di or '<unknown>'}")


def same_file_info(
    info: dict[str, Any],
    *,
    file_type: int,
    file_id: int,
    dest_address: str,
    package: SegmentedFile,
) -> bool:
    file_crc = info.get("file_crc") or info.get("file_crc16")
    if isinstance(file_crc, str):
        file_crc = int(file_crc.replace("0x", "").replace("0X", ""), 16)
    return (
        int(info.get("file_type", -1)) == file_type
        and int(info.get("file_id", -1)) == file_id
        and str(info.get("dest_addr") or info.get("dest_address", "")) == dest_address
        and int(info.get("total_segments", -1)) == package.total_segments
        and int(info.get("file_size", -1)) == package.size
        and int(file_crc or -1) == package.crc16
    )


def clear_file_info_payload(dest_address: str) -> dict[str, Any]:
    return {
        "file_type": 0,
        "file_id": 0,
        "dest_addr": dest_address,
        "total_segments": 0,
        "file_size": 0,
        "file_crc": 0,
        "timeout_minutes": 0,
    }


def start_file_info_payload(
    *,
    file_type: int,
    file_id: int,
    dest_address: str,
    package: SegmentedFile,
    timeout_minutes: int,
) -> dict[str, Any]:
    return {
        "file_type": file_type,
        "file_id": file_id,
        "dest_addr": dest_address,
        "total_segments": package.total_segments,
        "file_size": package.size,
        "file_crc": package.crc16,
        "timeout_minutes": timeout_minutes,
    }


def segment_payload(segment: FileSegment) -> dict[str, Any]:
    return {
        "segment_index": segment.number,
        "segment_length": segment.length,
        "segment_data": segment.data,
        "segment_crc": segment.crc16,
    }


def cache_is_valid(cache: dict[str, Any], *, file_hash: str, segment_size: int, params: dict[str, Any]) -> bool:
    if cache.get("version") != CACHE_VERSION:
        return False
    if cache.get("crc_algo") != CACHE_CRC_ALGO:
        return False
    if cache.get("file_hash") != file_hash:
        return False
    if cache.get("segment_size") != segment_size:
        return False
    if cache.get("params") != params:
        return False
    return isinstance(cache.get("segments"), list) and bool(cache["segments"])


def _chunks(data: bytes, size: int) -> list[bytes]:
    if not data:
        return [b""]
    return [data[index:index + size] for index in range(0, len(data), size)]


def _find_decoded_value(values: dict[str, Any], leaf_name: str) -> Any:
    for container_name in ("data_content", "user_data"):
        container = values.get(container_name)
        if isinstance(container, dict):
            if leaf_name in container:
                return container[leaf_name]
            suffix = f".{leaf_name}"
            for key, value in container.items():
                if str(key).endswith(suffix):
                    return value
    return values.get(leaf_name)
