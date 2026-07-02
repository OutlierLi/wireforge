"""/wait-frame 命令处理器 — 监听串口，decode 帧并匹配 expect 条件。

用法:
  /wait-frame --to cco --timeout 5000 \\
    --protocol csg \\
    --expect.afn 04 --expect.fn Fn12 --expect.dir uplink \\
    --expect.user_data.result success,start

成功时返回:
  {"status": "success", "matched": true, "elapsed_ms": 842,
   "frame_hex": "68 ... 16", "decoded": {...}}

失败时返回:
  {"status": "fail", "matched": false, "timeout_ms": 5000,
   "received_frames": 7, "decoded_frames": 5, "last_decoded": {...},
   "mismatch_summary": [...]}
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from console.arg_utils import parse_timeout_ms
from console.handlers.frame_splitter import split_frames
from console.response import ok, fail
ROOT = Path(__file__).resolve().parent.parent.parent


def handle(args: dict[str, Any]) -> dict:
    from lab_service import get_lab_service

    lab = get_lab_service()
    args = lab.normalize_args(args)
    target = lab.connection_id(args) or "default"
    timeout_ms = parse_timeout_ms(args.get("timeout"), default=5000)
    protocol = str(args.get("proto") or args.get("protocol", ""))

    # 检查串口连接
    transport = lab.get_connection(target)
    if not transport:
        return fail(
            f"serial not connected (to={target}). "
            f"use /serial connect --name {target} --port <port> first"
        )

    # 解析 expect 条件
    expect = _parse_expect(args)
    if not expect:
        return fail("no expect conditions provided. Use --expect.afn, --expect.di, --expect.dir, --expect.user_data.* etc.")

    deadline = time.monotonic() + timeout_ms / 1000.0
    buffer = bytearray()
    received_count = 0
    decoded_count = 0
    last_decoded: dict[str, Any] = {}
    mismatch_summary: list[str] = []
    poll_interval = 0.02  # 20ms poll

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        chunk = transport.read_response(min(0.2, remaining))
        if chunk:
            buffer.extend(chunk)

        data = bytes(buffer)
        frames, remainder = split_frames(data)
        buffer = bytearray(remainder)

        for idx, frame_bytes in enumerate(frames):
            received_count += 1
            frame_hex = frame_bytes.hex(" ").upper()

            decoded = _try_decode(frame_bytes, protocol)
            if decoded is None:
                mismatch_summary.append(f"frame[{received_count}]: decode failed")
                continue

            decoded_count += 1
            last_decoded = decoded

            match_result = _match_expect(decoded, expect, received_count)
            if match_result is True:
                leftover = b"".join(frames[idx + 1:]) + bytes(remainder)
                if leftover:
                    transport.prepend_rx(leftover)
                elapsed_ms = int((time.monotonic() - (deadline - timeout_ms / 1000.0)) * 1000)
                return ok({
                    "matched": True,
                    "elapsed_ms": elapsed_ms,
                    "frame_hex": frame_hex,
                    "decoded": decoded,
                    "frame_index": received_count,
                })

            mismatch_summary.append(match_result)

        time.sleep(poll_interval)

    return fail("timeout: no frame matched expect conditions", detail={
        "matched": False,
        "timeout_ms": timeout_ms,
        "received_frames": received_count,
        "decoded_frames": decoded_count,
        "last_decoded": last_decoded,
        "mismatch_summary": mismatch_summary,
    })


# ── expect 解析 ────────────────────────────────────────────────────────

def _parse_expect(args: dict[str, Any]) -> list[dict[str, Any]] | None:
    """从命令行参数解析 expect 条件为内部匹配格式。

    支持两种格式:
    1. --expect.afn=04 --expect.dir=uplink --expect.user_data.result=success
    2. --expect='{"all":[...]}'  直接传 JSON

    内部格式: [{"path": "$.afn", "op": "eq", "value": "04"}, ...]
    """
    raw_expect = args.get("expect")
    if isinstance(raw_expect, str):
        try:
            parsed = json.loads(raw_expect)
            if isinstance(parsed, dict):
                return _normalize_expect_dict(parsed)
        except json.JSONDecodeError:
            pass

    # 从 --expect.xxx 参数构建
    conditions: list[dict[str, Any]] = []
    for key, val in args.items():
        if key.startswith("expect.") and val is not None:
            path = "$." + key[len("expect."):]
            conditions.append(_make_condition(path, str(val)))

    return conditions if conditions else None


def _normalize_expect_dict(expect: dict[str, Any]) -> list[dict[str, Any]]:
    """将 {'all': [...], 'any': [...]} 格式扁平化为条件列表。"""
    if "all" in expect:
        return list(expect["all"])
    if "any" in expect:
        return [{"_or": list(expect["any"])}]
    return []


def _make_condition(path: str, value_str: str) -> dict[str, Any]:
    """从路径和值字符串构建匹配条件。"""
    # 支持逗号分隔的多值: "success,start" → any of these values
    if "," in value_str:
        values = [v.strip() for v in value_str.split(",")]
        return {"path": path, "op": "in", "value": values}
    return {"path": path, "op": "eq", "value": value_str}


# ── decode ──────────────────────────────────────────────────────────────

def _try_decode(frame: bytes, protocol: str) -> dict[str, Any] | None:
    """尝试解码帧，返回扁平化的 decoded dict。"""
    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine

    # 映射用户短名到内部协议名
    _proto_map = {"csg": "csg_2016", "dlt645": "dlt645_2007"}
    proto_full = _proto_map.get(protocol, protocol)
    protocols = [proto_full] if proto_full else ["csg_2016", "dlt645_2007"]
    for proto in protocols:
        try:
            ir_path = ROOT / "compiled" / f"{proto}.ir.json"
            if not ir_path.exists():
                continue
            ir = ProtocolIR.from_json_file(str(ir_path))
            de = DecodeEngine(ir, create_builtin_registry())
            result = de.decode(frame)
            # Build a clean decoded dict
            decoded = _flatten_decode_values(result.values, result.path_str)
            decoded["protocol"] = proto
            return decoded
        except Exception:
            continue
    return None


def _flatten_decode_values(values: dict[str, Any], path: str) -> dict[str, Any]:
    """从 IR decode values 提取关键字段为扁平 dict。

    提取: control (dir, add), afn, di, user_data 中的业务字段。
    处理 CSG 的命名空间前缀如 csg_downlink.afn。
    """
    result: dict[str, Any] = {}

    control = values.get("control")
    if isinstance(control, dict):
        result["dir"] = "uplink" if control.get("dir") == 1 else "downlink"
        result["add"] = control.get("add", 0)
        func_val = control.get("func")
        if func_val is not None:
            result["func"] = int(func_val)

    # 收集所有 key-value，处理命名空间前缀
    all_pairs: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(val, dict):
            continue  # nested dicts handled by user_data
        # 提取短名: csg_downlink.afn → afn, slave_count → slave_count
        short = key.rsplit(".", 1)[-1] if "." in key else key
        if short not in all_pairs:
            all_pairs[short] = val
        # 也保留全名用于精确匹配
        all_pairs[key] = val

    # afn
    afn_val = all_pairs.get("afn")
    if afn_val is not None:
        result["afn"] = f"0x{int(afn_val):02X}"

    # di
    di_val = all_pairs.get("di")
    if di_val is not None:
        result["di"] = str(di_val).replace(" ", "").upper()

    # seq
    seq_val = all_pairs.get("seq")
    if seq_val is not None:
        result["seq"] = int(seq_val)

    # DLT645: data 块（di 等）
    data = values.get("data")
    if isinstance(data, dict):
        for key, val in data.items():
            if key == "di" and val is not None:
                di_norm = str(val).replace(" ", "").upper()
                result["di"] = di_norm
                result["user_data.di"] = di_norm
            elif not isinstance(val, (dict, list)):
                result[f"user_data.{key}"] = str(val)

    # 提取 user_data 中的业务字段
    ud = values.get("user_data")
    if isinstance(ud, dict):
        for key, val in ud.items():
            short = key.rsplit(".", 1)[-1] if "." in key else key
            if not isinstance(val, (dict, list)):
                result[f"user_data.{short}"] = str(val)
            elif isinstance(val, list) and len(val) <= 10:
                result[f"user_data.{short}"] = val

    # 提取所有非嵌套的标量字段（已去除帧头公共字段）
    skip_fields = {"start", "total_length", "checksum", "end",
                   "control", "user_data", "afn", "di", "seq", "dir", "add"}
    for key, val in all_pairs.items():
        short = key.rsplit(".", 1)[-1] if "." in key else key
        if short in skip_fields:
            continue
        if isinstance(val, (str, int, float)):
            # 跳过已经通过 user_data 添加的
            if short not in {k.replace("user_data.", "") for k in result}:
                result[short] = str(val) if isinstance(val, str) else val

    return result


# ── match ───────────────────────────────────────────────────────────────

def _match_expect(decoded: dict[str, Any], conditions: list[dict[str, Any]],
                  frame_index: int) -> bool | str:
    """检查 decoded 是否满足所有 expect 条件。

    Returns:
        True if all match
        str mismatch description if any fail
    """
    for cond in conditions:
        if not _eval_condition(decoded, cond):
            path = cond.get("path", "?")
            op = cond.get("op", "eq")
            expected = cond.get("value", "?")
            actual = _get_by_path(decoded, path)
            return f"frame[{frame_index}]: {path} expected {op} {_norm_val(expected)}, actual {_norm_val(actual)}"
    return True


def _eval_condition(data: dict[str, Any], condition: dict[str, Any]) -> bool:
    """Evaluate a single condition."""
    path = condition.get("path", "")
    op = condition.get("op", "eq")
    expected = condition.get("value")

    actual = _get_by_path(data, path)

    if op == "eq":
        return _norm_val(actual) == _norm_val(expected)
    if op == "neq":
        return _norm_val(actual) != _norm_val(expected)
    if op == "in":
        expected_list = expected if isinstance(expected, list) else [expected]
        return _norm_val(actual) in [_norm_val(v) for v in expected_list]
    if op == "contains":
        return _norm_val(expected) in _norm_val(actual)
    if op == "exists":
        return actual is not None
    if op == "gt":
        try:
            return float(actual) > float(expected)
        except (ValueError, TypeError):
            return False
    if op == "lt":
        try:
            return float(actual) < float(expected)
        except (ValueError, TypeError):
            return False
    return False


def _norm_val(val: Any) -> str:
    """Normalize a value for comparison: strip 0x prefix, lowercase, trim whitespace."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    # Normalize hex: 0x03 → 03, E8 00 03 01 → e8000301
    if s.startswith("0x"):
        s = s[2:]
    s = s.replace(" ", "")
    return s


def _get_by_path(data: dict[str, Any], path: str) -> Any:
    """Get value from nested dict using JSONPath-like syntax.

    "$.afn" → data["afn"]
    "$.user_data.result" → data["user_data"]["result"]
    """
    if path.startswith("$."):
        path = path[2:]
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
