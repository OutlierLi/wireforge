"""DLT645-2007 请求-响应配对表加载与展开。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

from tests.protocol_info import DLT645_DI_VARIANTS

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = _PROJECT_ROOT / "protocol_tool" / "protocols" / "dlt645_2007" / "dlt645_message_pairs.yaml"

_VALID_DIRS = frozenset({"downlink", "uplink"})
_FUNC_RE = re.compile(r"^[0-9A-Fa-f]{1,2}$")
_HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")

DOWNLINK_COVERAGE = [
    ("03", None, None),
    ("08", None, None),
    ("11", None, None),
    ("12", None, None),
    ("13", None, None),
    ("15", None, None),
    ("16", "00000000", None),
    ("16", "00010000", None),
    ("16", "00010001", None),
    ("17", None, None),
    ("18", None, None),
    ("19", None, None),
    ("1A", None, None),
    ("1B", None, "00991B01"),
    ("1C", None, None),
    ("1D", None, None),
]


@dataclass
class Dlt645PairMessage:
    pair_id: str
    side: str
    slot: str
    role: str | None
    func: str
    dir: str
    di: str | None = None
    freeze_type: str | None = None
    event_type: str | None = None
    frame_defaults: dict[str, Any] = field(default_factory=dict)
    field_defaults: dict[str, Any] = field(default_factory=dict)


def _validate_func(func: str, ctx: str) -> str:
    func = str(func).upper()
    if not _FUNC_RE.match(func):
        raise ValueError(f"{ctx}: invalid func {func!r}")
    return func


def _validate_dir(direction: str, ctx: str) -> str:
    direction = str(direction).lower()
    if direction not in _VALID_DIRS:
        raise ValueError(f"{ctx}: invalid dir {direction!r}")
    return direction


def _optional_hex8(value: Any, ctx: str, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value).upper()
    if not _HEX8_RE.match(text):
        raise ValueError(f"{ctx}: invalid {field_name} {value!r}")
    return text


def _parse_message(msg: dict[str, Any], ctx: str) -> dict[str, Any]:
    if not isinstance(msg, dict):
        raise ValueError(f"{ctx}: message must be a mapping")
    if "func" not in msg or "dir" not in msg:
        raise ValueError(f"{ctx}: missing required field func or dir")
    di = msg.get("di")
    if di is not None:
        di = str(di).upper()
    return {
        "func": _validate_func(msg["func"], ctx),
        "dir": _validate_dir(msg["dir"], ctx),
        "di": di,
        "freeze_type": _optional_hex8(msg.get("freeze_type"), ctx, "freeze_type"),
        "event_type": _optional_hex8(msg.get("event_type"), ctx, "event_type"),
        "frame_defaults": dict(msg.get("frame_defaults") or {}),
        "field_defaults": dict(msg.get("field_defaults") or {}),
    }


def _read_pairs_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("dlt645_message_pairs.yaml root must be a mapping")
    if data.get("version") != 1:
        raise ValueError(f"unsupported pairs version: {data.get('version')!r}")
    pairs_raw = data.get("pairs")
    if not isinstance(pairs_raw, list):
        raise ValueError("pairs must be a list")
    return data


def _parse_pair(pair: dict[str, Any], ctx: str) -> dict[str, Any]:
    if not isinstance(pair, dict):
        raise ValueError(f"{ctx}: pair must be a mapping")
    pair_id = pair.get("id")
    if not pair_id or not isinstance(pair_id, str):
        raise ValueError(f"{ctx}: missing pair id")

    request = _parse_message(pair["request"], f"{ctx}.request")
    responses_raw = pair.get("responses") or []
    if not isinstance(responses_raw, list):
        raise ValueError(f"{ctx}.responses must be a list")

    responses: list[dict[str, Any]] = []
    for j, resp in enumerate(responses_raw):
        rctx = f"{ctx}.responses[{j}]"
        if not isinstance(resp, dict):
            raise ValueError(f"{rctx}: response must be a mapping")
        parsed = _parse_message(resp, rctx)
        role = resp.get("role")
        if role is not None and not isinstance(role, str):
            raise ValueError(f"{rctx}: role must be a string")
        repeat = resp.get("repeat", 1)
        if not isinstance(repeat, int) or repeat < 1:
            raise ValueError(f"{rctx}: repeat must be a positive integer")
        parsed["role"] = role
        parsed["repeat"] = repeat
        responses.append(parsed)

    return {
        "id": pair_id,
        "request": request,
        "responses": responses,
        "field_defaults": dict(pair.get("field_defaults") or {}),
        "frame_defaults": dict(pair.get("frame_defaults") or {}),
    }


def _expand_read_data_pairs() -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for di_hex, _desc, _fields in DLT645_DI_VARIANTS:
        di = di_hex.upper()
        pairs.append({
            "id": f"read_data_{di.lower()}",
            "request": {
                "func": "11",
                "dir": "downlink",
                "di": di,
                "field_defaults": {"di": di},
            },
            "responses": [{
                "role": "data",
                "func": "11",
                "dir": "uplink",
                "di": di,
                "field_defaults": {"di": di},
            }],
        })
    return pairs


def load_dlt645_pairs(path: Path | None = None) -> dict[str, Any]:
    """加载并校验 dlt645_message_pairs.yaml（含读数据 DI 变体展开）。"""
    path = path or PAIRS_PATH
    root = _read_pairs_yaml(path)
    pairs_raw = root["pairs"]

    pairs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, pair in enumerate(pairs_raw):
        parsed = _parse_pair(pair, f"pairs[{i}]")
        if parsed["id"] in seen_ids:
            raise ValueError(f"duplicate pair id: {parsed['id']}")
        seen_ids.add(parsed["id"])
        pairs.append(parsed)

    for pair in _expand_read_data_pairs():
        if pair["id"] in seen_ids:
            continue
        pairs.append(_parse_pair(pair, f"read_data[{pair['id']}]"))
        seen_ids.add(pair["id"])

    return {"version": 1, "exclude": root.get("exclude") or [], "pairs": pairs}


def _msg_to_pair_message(
    pair_id: str,
    side: str,
    slot: str,
    role: str | None,
    msg: dict[str, Any],
    pair: dict[str, Any],
) -> Dlt645PairMessage:
    pair_defaults = pair.get("field_defaults") or {}
    pair_frame = pair.get("frame_defaults") or {}
    merged_fields = {**pair_defaults, **msg.get("field_defaults", {})}
    if side == "request":
        merged_frame = {**pair_frame, **msg.get("frame_defaults", {})}
    else:
        merged_frame = dict(msg.get("frame_defaults") or {})
    return Dlt645PairMessage(
        pair_id=pair_id,
        side=side,
        slot=slot,
        role=role,
        func=msg["func"],
        dir=msg["dir"],
        di=msg.get("di"),
        freeze_type=msg.get("freeze_type"),
        event_type=msg.get("event_type"),
        frame_defaults=merged_frame,
        field_defaults=merged_fields,
    )


def iter_pair_messages(pair: dict[str, Any]) -> Iterator[Dlt645PairMessage]:
    """展开 request 与 responses（含 repeat）为逐条测试消息。"""
    pair_id = pair["id"]
    yield _msg_to_pair_message(pair_id, "request", "request", None, pair["request"], pair)

    for resp in pair.get("responses") or []:
        repeat = resp.get("repeat", 1)
        for n in range(1, repeat + 1):
            slot = f"response#{n}" if repeat > 1 else "response"
            yield _msg_to_pair_message(pair_id, "response", slot, resp.get("role"), resp, pair)


def to_route_info(msg: Dlt645PairMessage | dict[str, Any]) -> dict[str, Any]:
    """转为 BuildEngine.resolve_path 所需的 info dict。"""
    if isinstance(msg, Dlt645PairMessage):
        func = int(msg.func, 16)
        direction = msg.dir
        di = msg.di
        freeze_type = msg.freeze_type
        event_type = msg.event_type
    else:
        func = int(msg["func"], 16)
        direction = msg["dir"]
        di = msg.get("di")
        freeze_type = msg.get("freeze_type")
        event_type = msg.get("event_type")

    info: dict[str, Any] = {"func": func, "direction": direction}
    if di:
        info["di"] = di
    if freeze_type:
        info["freeze_type"] = freeze_type
    if event_type:
        info["event_type"] = event_type
    return info


def request_keys_from_pairs(pairs_data: dict[str, Any]) -> set[tuple[str, str | None, str | None]]:
    keys: set[tuple[str, str | None, str | None]] = set()
    for pair in pairs_data["pairs"]:
        req = pair["request"]
        keys.add((
            req["func"].upper(),
            req.get("freeze_type"),
            req.get("event_type"),
        ))
    return keys


def validate_downlink_coverage(pairs_data: dict[str, Any]) -> list[str]:
    """返回未覆盖的 protocol_map 主动下行条目。"""
    covered = request_keys_from_pairs(pairs_data)
    missing = []
    for func, freeze_type, event_type in DOWNLINK_COVERAGE:
        key = (func.upper(), freeze_type, event_type)
        if key not in covered:
            extra = []
            if freeze_type:
                extra.append(f"freeze_type={freeze_type}")
            if event_type:
                extra.append(f"event_type={event_type}")
            suffix = f" ({', '.join(extra)})" if extra else ""
            missing.append(f"func={func}{suffix}")
    return missing


def message_label(msg: dict[str, Any]) -> str:
    """生成链路标签，如 func11/00010000 或 func16/00010000。"""
    func = int(str(msg["func"]), 16)
    token = f"func{func:02x}"
    if msg.get("di"):
        token += f"/{str(msg['di']).lower()}"
    if msg.get("freeze_type"):
        token += f"/{str(msg['freeze_type']).lower()}"
    if msg.get("event_type"):
        token += f"/{str(msg['event_type']).lower()}"
    return token


def format_pair_chain(pair: dict[str, Any]) -> str:
    """生成测试项目链，如 func11/00010000 ---> [func11/00010000]。"""
    req_label = message_label(pair["request"])
    resp_tokens: list[str] = []
    for resp in pair.get("responses") or []:
        token = message_label(resp)
        repeat = int(resp.get("repeat", 1))
        resp_tokens.extend([token] * repeat)
    if resp_tokens:
        return f"{req_label} ---> [{', '.join(resp_tokens)}]"
    return f"{req_label} ---> []"


def serial_trace_lines(pair: dict[str, Any], pair_results: list[Any]) -> list[str]:
    """从配对测试结果生成串口 TX/RX 日志行。"""
    lines: list[str] = []
    messages = list(iter_pair_messages(pair))
    for msg, result in zip(messages, pair_results):
        if getattr(result, "status", None) != "PASS":
            continue
        frame_hex = getattr(result, "frame_hex", "") or ""
        if not frame_hex:
            continue
        direction = "TX" if msg.dir == "downlink" else "RX"
        lines.append(f"{direction}: {frame_hex}")
    return lines
