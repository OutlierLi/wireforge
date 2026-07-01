"""CSG 2016 请求-响应配对表加载与展开。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = _PROJECT_ROOT / "protocol_tool" / "protocols" / "csg_2016" / "csg_message_pairs.yaml"

_VALID_DIRS = frozenset({"downlink", "uplink"})
_DI_RE = re.compile(r"^E[0-9A-Fa-f]{6,8}$")
_AFN_RE = re.compile(r"^[0-9A-Fa-f]{2}$")

# 表4 全部主动下行（与 test_protocol_agent_mcp.pdf_table4 一致）
PDF_TABLE4_DOWNLINK = [
    ("00", "E8010001"),
    ("00", "E8010002"),
    ("01", "E8020101"),
    ("01", "E8020102"),
    ("01", "E8020103"),
    ("02", "E8020201"),
    ("02", "E8020202"),
    ("02", "E8000203"),
    ("02", "E8030204"),
    ("02", "E8030205"),
    ("02", "E8000206"),
    ("02", "E8020207"),
    ("02", "E8020208"),
    ("02", "E8020209"),
    ("03", "E8000301"),
    ("03", "E8000302"),
    ("03", "E8000303"),
    ("03", "E8030304"),
    ("03", "E8000305"),
    ("03", "E8030306"),
    ("03", "E8000307"),
    ("03", "E8030308"),
    ("04", "E8020401"),
    ("04", "E8020402"),
    ("04", "E8020403"),
    ("04", "E8020404"),
    ("04", "E8020405"),
    ("04", "E8020406"),
    ("06", "E8060601"),
    ("07", "E8020701"),
    ("07", "E8020702"),
    ("07", "E8000703"),
    ("07", "E8000704"),
    ("07", "E8030704"),
]


@dataclass
class PairMessage:
    pair_id: str
    scenario_id: str
    side: str  # "request" | "response"
    slot: str  # e.g. "request", "response#1"
    role: str | None
    afn: str
    di: str
    dir: str
    has_address: bool = False
    field_defaults: dict[str, Any] = field(default_factory=dict)


def _validate_afn(afn: str, ctx: str) -> str:
    afn = str(afn).upper()
    if not _AFN_RE.match(afn):
        raise ValueError(f"{ctx}: invalid afn {afn!r}")
    return afn


def _validate_di(di: str, ctx: str) -> str:
    di = str(di).upper()
    if not _DI_RE.match(di):
        raise ValueError(f"{ctx}: invalid di {di!r}")
    return di


def _validate_dir(direction: str, ctx: str) -> str:
    direction = str(direction).lower()
    if direction not in _VALID_DIRS:
        raise ValueError(f"{ctx}: invalid dir {direction!r}")
    return direction


def _parse_message(msg: dict[str, Any], ctx: str) -> dict[str, Any]:
    if not isinstance(msg, dict):
        raise ValueError(f"{ctx}: message must be a mapping")
    required = ("afn", "di", "dir")
    for key in required:
        if key not in msg:
            raise ValueError(f"{ctx}: missing required field {key!r}")
    return {
        "afn": _validate_afn(msg["afn"], ctx),
        "di": _validate_di(msg["di"], ctx),
        "dir": _validate_dir(msg["dir"], ctx),
        "has_address": bool(msg.get("has_address", False)),
        "field_defaults": dict(msg.get("field_defaults") or {}),
    }


def _parse_response_list(items: Any, ctx: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{ctx} must be a list")

    responses: list[dict[str, Any]] = []
    for j, resp in enumerate(items):
        rctx = f"{ctx}[{j}]"
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
    return responses


def _parse_response_scenarios(pair: dict[str, Any], ctx: str) -> list[dict[str, Any]]:
    if "response_scenarios" not in pair:
        return [{"id": "default", "responses": _parse_response_list(pair.get("responses") or [], f"{ctx}.responses")}]

    scenarios_raw = pair.get("response_scenarios")
    if not isinstance(scenarios_raw, list) or not scenarios_raw:
        raise ValueError(f"{ctx}.response_scenarios must be a non-empty list")

    scenarios: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for j, scenario in enumerate(scenarios_raw):
        sctx = f"{ctx}.response_scenarios[{j}]"
        if not isinstance(scenario, dict):
            raise ValueError(f"{sctx}: scenario must be a mapping")
        scenario_id = scenario.get("id")
        if not scenario_id or not isinstance(scenario_id, str):
            raise ValueError(f"{sctx}: missing scenario id")
        if scenario_id in seen_ids:
            raise ValueError(f"{sctx}: duplicate scenario id {scenario_id!r}")
        seen_ids.add(scenario_id)
        responses = _parse_response_list(scenario.get("responses") or [], f"{sctx}.responses")
        scenarios.append({"id": scenario_id, "responses": responses})
    return scenarios


def load_csg_pairs(path: Path | None = None) -> dict[str, Any]:
    """加载并校验 csg_message_pairs.yaml。"""
    path = path or PAIRS_PATH
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("csg_message_pairs.yaml root must be a mapping")
    if data.get("version") != 1:
        raise ValueError(f"unsupported pairs version: {data.get('version')!r}")

    pairs_raw = data.get("pairs")
    if not isinstance(pairs_raw, list) or not pairs_raw:
        raise ValueError("pairs must be a non-empty list")

    pairs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, pair in enumerate(pairs_raw):
        ctx = f"pairs[{i}]"
        if not isinstance(pair, dict):
            raise ValueError(f"{ctx}: pair must be a mapping")
        pair_id = pair.get("id")
        if not pair_id or not isinstance(pair_id, str):
            raise ValueError(f"{ctx}: missing pair id")
        if pair_id in seen_ids:
            raise ValueError(f"duplicate pair id: {pair_id}")
        seen_ids.add(pair_id)

        request = _parse_message(pair["request"], f"{ctx}.request")
        response_scenarios = _parse_response_scenarios(pair, ctx)
        responses = response_scenarios[0]["responses"] if response_scenarios else []

        pairs.append({
            "id": pair_id,
            "request": request,
            "responses": responses,
            "response_scenarios": response_scenarios,
            "field_defaults": dict(pair.get("field_defaults") or {}),
        })

    return {"version": 1, "exclude": data.get("exclude") or [], "pairs": pairs}


def iter_pair_messages(pair: dict[str, Any]) -> Iterator[PairMessage]:
    """Expand request and every response scenario into test messages."""
    pair_id = pair["id"]
    pair_defaults = pair.get("field_defaults") or {}
    req = pair["request"]

    for scenario in iter_pair_scenarios(pair):
        scenario_id = scenario["id"]
        slot_prefix = "" if scenario_id == "default" else f"{scenario_id}:"
        yield PairMessage(
            pair_id=pair_id,
            scenario_id=scenario_id,
            side="request",
            slot=f"{slot_prefix}request",
            role=None,
            afn=req["afn"],
            di=req["di"],
            dir=req["dir"],
            has_address=req["has_address"],
            field_defaults={**pair_defaults, **req.get("field_defaults", {})},
        )

        for resp in scenario.get("responses") or []:
            repeat = resp.get("repeat", 1)
            for n in range(1, repeat + 1):
                response_slot = f"response#{n}" if repeat > 1 else "response"
                yield PairMessage(
                    pair_id=pair_id,
                    scenario_id=scenario_id,
                    side="response",
                    slot=f"{slot_prefix}{response_slot}",
                    role=resp.get("role"),
                    afn=resp["afn"],
                    di=resp["di"],
                    dir=resp["dir"],
                    has_address=resp["has_address"],
                    field_defaults={**pair_defaults, **resp.get("field_defaults", {})},
                )


def iter_pair_scenarios(pair: dict[str, Any]) -> Iterator[dict[str, Any]]:
    scenarios = pair.get("response_scenarios") or [{"id": "default", "responses": pair.get("responses") or []}]
    yield from scenarios


def iter_pair_scenario_messages(pair: dict[str, Any], scenario_id: str) -> Iterator[PairMessage]:
    scenario = next((item for item in iter_pair_scenarios(pair) if item["id"] == scenario_id), None)
    if scenario is None:
        raise ValueError(f"unknown scenario {scenario_id!r} for pair {pair['id']}")
    pair_copy = dict(pair)
    pair_copy["response_scenarios"] = [scenario]
    yield from iter_pair_messages(pair_copy)


def _afn_to_int(afn: str) -> int:
    return int(str(afn), 16)


def to_route_info(msg: PairMessage | dict[str, Any]) -> dict[str, Any]:
    """转为 BuildEngine.resolve_path 所需的 info dict。"""
    if isinstance(msg, PairMessage):
        return {
            "afn": _afn_to_int(msg.afn),
            "di": msg.di,
            "direction": msg.dir,
            "has_address": msg.has_address,
        }
    return {
        "afn": _afn_to_int(msg["afn"]),
        "di": msg["di"],
        "direction": msg["dir"],
        "has_address": bool(msg.get("has_address", False)),
    }


def request_keys_from_pairs(pairs_data: dict[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for pair in pairs_data["pairs"]:
        req = pair["request"]
        keys.add((req["afn"], req["di"]))
    return keys


def validate_table4_coverage(pairs_data: dict[str, Any]) -> list[str]:
    """返回未覆盖的表4 downlink (afn, di) 列表。"""
    covered = request_keys_from_pairs(pairs_data)
    missing = []
    for afn, di in PDF_TABLE4_DOWNLINK:
        if (afn, di) not in covered:
            missing.append(f"AFN={afn} DI={di}")
    return missing


def di_label(di: str) -> str:
    """DI 展示标签（小写，如 e8020201）。"""
    return str(di).lower()


def format_pair_di_chain(pair: dict[str, Any], scenario_id: str | None = None) -> str:
    """生成测试项目链，如 e8020201 ---> [e8010001, e8050501, e8050501]。"""
    req_di = di_label(pair["request"]["di"])
    scenarios = list(iter_pair_scenarios(pair))
    scenario = next((item for item in scenarios if item["id"] == scenario_id), scenarios[0])
    resp_tokens: list[str] = []
    for resp in scenario.get("responses") or []:
        token = di_label(resp["di"])
        repeat = int(resp.get("repeat", 1))
        resp_tokens.extend([token] * repeat)
    if resp_tokens:
        return f"{req_di} ---> [{', '.join(resp_tokens)}]"
    return f"{req_di} ---> []"


def serial_trace_lines(
    pair: dict[str, Any],
    pair_results: list[Any],
) -> list[str]:
    """从配对测试结果生成串口 TX/RX 日志行（仅含 TX/RX 与 hex）。"""
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
