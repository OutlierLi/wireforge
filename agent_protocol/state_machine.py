"""Recoverable state machine for natural-language protocol tasks.

V1 is intentionally conservative: it uses deterministic task/protocol
classification, records every run under agent_protocol_runs/<run_id>, and calls
business handlers with structured dictionaries instead of CLI command strings.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from console.handlers import build as build_handler
from console.handlers import decode as decode_handler
from knowledge_base.store import search as kb_search
from wireforge_serial.api import get_connection, serial_send


ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "agent_protocol_runs"
LOG_DIR = ROOT / "log"
WORKFLOW_LOG = LOG_DIR / "agent_protocol_workflow.log"

TaskType = Literal["BUILD", "DECODE", "SEND"]
RunState = Literal[
    "INIT",
    "CONTEXT_READY",
    "PLAN_READY",
    "EXECUTING",
    "WAITING_INPUT",
    "FAILED",
    "SUCCEEDED",
]


@dataclass
class TaskPlan:
    tasks: list[TaskType] = field(default_factory=list)
    current_index: int = 0
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "current_index": self.current_index,
            "completed": self.completed,
            "pending": self.pending,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        return cls(
            tasks=list(data.get("tasks") or []),
            current_index=int(data.get("current_index") or 0),
            completed=list(data.get("completed") or []),
            pending=list(data.get("pending") or []),
            dependencies=dict(data.get("dependencies") or {}),
        )


@dataclass
class RunRecord:
    run_id: str
    raw_input: str
    state: RunState = "INIT"
    context: dict[str, Any] = field(default_factory=dict)
    task_plan: TaskPlan = field(default_factory=TaskPlan)
    facts: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    waiting_input: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "raw_input": self.raw_input,
            "state": self.state,
            "context": self.context,
            "task_plan": self.task_plan.to_dict(),
            "facts": self.facts,
            "results": self.results,
            "waiting_input": self.waiting_input,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(data["run_id"]),
            raw_input=str(data.get("raw_input") or ""),
            state=str(data.get("state") or "INIT"),  # type: ignore[arg-type]
            context=dict(data.get("context") or {}),
            task_plan=TaskPlan.from_dict(dict(data.get("task_plan") or {})),
            facts=dict(data.get("facts") or {}),
            results=dict(data.get("results") or {}),
            waiting_input=dict(data.get("waiting_input") or {}),
            error=str(data.get("error") or ""),
        )


def run_agent_protocol(
    raw_input: str | None = None,
    *,
    run_id: str | None = None,
    user_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance a protocol task run and persist its state."""

    record = _load_or_create(run_id, raw_input)
    _append_event(record, "enter", {"state": record.state, "user_input": user_input or {}})

    if raw_input and not record.raw_input:
        record.raw_input = raw_input
        _write_text(record, "raw_input", record.raw_input)

    if user_input:
        record.facts.update(_normalize_user_input(user_input))
        if record.state == "WAITING_INPUT":
            record.state = "EXECUTING"
            record.waiting_input = {}

    try:
        _advance(record)
    except Exception as exc:
        record.state = "FAILED"
        record.error = str(exc)
        _append_event(record, "failed_exception", {"error": str(exc)})

    _append_event(record, "round_exit", {
        "final_state": record.state,
        "waiting_input": record.waiting_input,
        "error": record.error,
        "final_result": record.results,
    })
    _save(record)
    return {
        "run_id": record.run_id,
        "state": record.state,
        "raw_input": record.raw_input,
        "context": record.context,
        "task_plan": record.task_plan.to_dict(),
        "waiting_input": record.waiting_input,
        "results": record.results,
        "error": record.error,
        "log_dir": str(_run_dir(record.run_id)),
        "workflow_log": str(WORKFLOW_LOG),
    }


def _advance(record: RunRecord) -> None:
    if record.state == "INIT":
        record.context = RagContextProvider().build_context(record.raw_input)
        record.state = "CONTEXT_READY"
        _write_json(record, "context", record.context)
        _append_event(record, "context_ready", _context_summary(record.context))

    if record.state == "CONTEXT_READY":
        plan_result = _plan_tasks(record.raw_input, record.context)
        if plan_result.get("not_supported"):
            record.state = "FAILED"
            record.error = "NOT_SUPPORTED"
            record.results["reason"] = plan_result["reason"]
            _append_event(record, "not_supported", plan_result)
            return
        record.task_plan = plan_result["plan"]
        record.facts.update(plan_result["facts"])
        record.state = "PLAN_READY"
        _write_json(record, "task_plan", record.task_plan.to_dict())
        _append_event(record, "plan_ready", plan_result["log"])

    if record.state == "PLAN_READY":
        record.state = "EXECUTING"

    if record.state == "EXECUTING":
        _execute_until_blocked(record)


class RagContextProvider:
    """Retrieve protocol knowledge chunks and produce a stable context shape."""

    def __init__(self, root: Path = ROOT):
        self.root = root

    def build_context(self, raw_input: str) -> dict[str, Any]:
        initial = kb_search(raw_input, top_k=6)
        protocol_tag = _dominant_protocol_tag(initial.get("results") or [])
        expanded_query = _expanded_context_query(raw_input)
        focused = kb_search(expanded_query, top_k=20, tag=protocol_tag) if protocol_tag else {"results": []}
        chunks = _merge_chunks(list(initial.get("results") or []) + list(focused.get("results") or []))
        sources = _context_sources(chunks)
        deterministic_fields: dict[str, Any] = {}
        if _mentions_current_time(raw_input):
            deterministic_fields["datetime"] = datetime.now().strftime("%y%m%d%H%M%S")
        facts = _facts_from_retrieved_context(raw_input, chunks, deterministic_fields)
        task_intents = _task_intents(raw_input)
        hints = _context_hints(chunks, facts)
        if re.search(r"\bCOM\d+\b", raw_input, re.IGNORECASE):
            hints.append({
                "kind": "serial",
                "summary": "用户输入中包含串口号。",
                "fields": ["port"],
                "certainty": "explicit",
            })

        return {
            "provider": "RagContextProvider",
            "sources": sources,
            "summary": "; ".join(item["summary"] for item in hints) or "知识库未返回明确协议上下文。",
            "hints": hints,
            "retrieved": [_context_chunk_summary(chunk) for chunk in chunks],
            "deterministic_fields": deterministic_fields,
            "facts": facts,
            "task_intents": task_intents,
            "value_aliases": {"dir": {"uplink": [1, "1"], "downlink": [0, "0"]}},
        }


def _task_intents(raw_input: str) -> dict[str, bool]:
    text = raw_input.lower()
    return {
        "build": any(word in raw_input for word in ["构造", "生成", "组帧", "回复", "响应"]) or "build" in text,
        "decode": any(word in raw_input for word in ["解析", "解码"]) or "decode" in text,
        "send": any(word in raw_input for word in ["发送", "下发", "写入", "执行"]) or "send" in text,
    }


def _expanded_context_query(raw_input: str) -> str:
    terms = [raw_input]
    if _mentions_current_time(raw_input):
        terms.append("datetime 当前时间")
    if _wants_response(raw_input):
        terms.append("response resp 响应 应答 上行")
    if _wants_request(raw_input):
        terms.append("request 请求 下行")
    return " ".join(terms)


def _mentions_current_time(raw_input: str) -> bool:
    return any(word in raw_input for word in ["当前时间", "当前日期", "现在时间", "系统时间"])


def _wants_response(raw_input: str) -> bool:
    return any(word in raw_input for word in ["响应", "应答", "回复", "返回"])


def _wants_request(raw_input: str) -> bool:
    return "请求" in raw_input and not _wants_response(raw_input)


def _dominant_protocol_tag(chunks: list[dict[str, Any]]) -> str | None:
    counts: dict[str, float] = {}
    for chunk in chunks:
        for tag in chunk.get("tags") or []:
            tag_text = str(tag)
            if re.fullmatch(r"[a-z0-9_]+_\d{4}", tag_text):
                counts[tag_text] = counts.get(tag_text, 0.0) + float(chunk.get("score") or 0.0)
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _merge_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        chunk_id = int(chunk.get("chunk_id") or 0)
        if not chunk_id:
            continue
        current = merged.get(chunk_id)
        if current is None or float(chunk.get("score") or 0.0) > float(current.get("score") or 0.0):
            merged[chunk_id] = chunk
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _context_sources(chunks: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    for chunk in chunks:
        path = str(chunk.get("path") or "")
        if path and path not in sources:
            sources.append(path)
    return sources


def _context_chunk_summary(chunk: dict[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("text") or "")
    return {
        "chunk_id": chunk.get("chunk_id"),
        "source_id": chunk.get("source_id"),
        "path": chunk.get("path"),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "score": chunk.get("score"),
        "text": text[:500],
    }


def _context_hints(chunks: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    if chunks:
        top = chunks[0]
        hints.append({
            "kind": "retrieval",
            "summary": f"知识库命中 {len(chunks)} 个候选片段，最高分来源 {top.get('path')}",
            "certainty": "candidate",
        })
    if facts:
        hints.append({
            "kind": "facts",
            "summary": "从知识库候选片段中提取到可执行参数。",
            "fields": sorted(facts.keys()),
            "certainty": "candidate",
        })
    return hints


def _facts_from_retrieved_context(raw_input: str, chunks: list[dict[str, Any]], deterministic_fields: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    proto = _explicit_proto(raw_input) or (_proto_from_chunks(chunks) if _raw_mentions_protocol_domain(raw_input) else "")
    if proto:
        facts["proto"] = proto
    if not _raw_has_explicit_route(raw_input):
        route_chunks = _chunks_for_proto(chunks, proto)
        route_chunk = _select_route_chunk(raw_input, route_chunks, deterministic_fields)
        route_text = str(route_chunk.get("text") or "") if route_chunk else ""
        if route_text:
            afn = _extract_afn(route_text)
            if afn:
                facts["afn"] = afn
            di = _extract_di(_select_route_block(raw_input, route_text, deterministic_fields))
            if di:
                facts["di"] = di
    if _wants_response(raw_input):
        facts["dir"] = "uplink"
    elif _wants_request(raw_input):
        facts["dir"] = "downlink"
    if deterministic_fields:
        facts["fields"] = dict(deterministic_fields)
    return facts


def _proto_from_chunks(chunks: list[dict[str, Any]]) -> str:
    for chunk in chunks:
        tags = [str(tag) for tag in chunk.get("tags") or []]
        if "csg_2016" in tags:
            return "csg"
        if "dlt645_2007" in tags:
            return "dlt645"
    return ""


def _explicit_proto(raw_input: str) -> str:
    text = raw_input.lower()
    if "dlt645" in text or "645" in text:
        return "dlt645"
    if "csg" in text or "南网" in raw_input:
        return "csg"
    return ""


def _raw_mentions_protocol_domain(raw_input: str) -> bool:
    return bool(_explicit_proto(raw_input) or any(word in raw_input for word in ["集中器", "采集器", "电表", "本地通信模块"]))


def _raw_has_explicit_route(raw_input: str) -> bool:
    return bool(
        re.search(r"(?:func|功能码)\s*[=: ]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]{2})", raw_input)
        or re.search(r"\bAFN\s*[=: ]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]{2})", raw_input, re.IGNORECASE)
        or re.search(r"\bDI\s*[=: ]\s*([0-9a-fA-F]{8})", raw_input, re.IGNORECASE)
    )


def _chunks_for_proto(chunks: list[dict[str, Any]], proto: str) -> list[dict[str, Any]]:
    if not proto:
        return chunks
    tag = "csg_2016" if proto == "csg" else "dlt645_2007" if proto == "dlt645" else proto
    filtered = [chunk for chunk in chunks if tag in [str(item) for item in chunk.get("tags") or []]]
    return filtered or chunks


def _select_route_chunk(raw_input: str, chunks: list[dict[str, Any]], deterministic_fields: dict[str, Any]) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        score = float(chunk.get("score") or 0.0)
        if "variant" in text or "message" in text:
            score += 0.15
        if _wants_response(raw_input) and re.search(r"\b(resp|response)\b|响应|应答|上行", text, re.I):
            score += 0.2
        if _wants_request(raw_input) and re.search(r"\brequest\b|请求|下行", text, re.I):
            score += 0.2
        for field in deterministic_fields:
            if field in text:
                score += 0.2
        if _extract_di(text):
            score += 0.1
        scored.append((score, chunk))
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def _select_route_block(raw_input: str, text: str, deterministic_fields: dict[str, Any]) -> str:
    blocks = re.split(r"(?=\n- kind:|\nid:)", "\n" + text)
    if len(blocks) <= 1:
        return text
    scored: list[tuple[float, str]] = []
    for block in blocks:
        score = 0.0
        if _wants_response(raw_input) and re.search(r"\b(resp|response)\b|响应|应答|上行", block, re.I):
            score += 2.0
        if _wants_request(raw_input) and re.search(r"\brequest\b|请求|下行", block, re.I):
            score += 2.0
        for field in deterministic_fields:
            if field in block:
                score += 1.0
        if _extract_di(block):
            score += 0.5
        scored.append((score, block))
    return max(scored, key=lambda item: item[0])[1]


def _extract_afn(text: str) -> str:
    if match := re.search(r"\bafn\s*:\s*(?:0x)?([0-9A-Fa-f]{1,2})", text, re.I):
        return match.group(1).zfill(2).upper()
    if match := re.search(r"\bAFN\s*[=＝]\s*(?:0x)?([0-9A-Fa-f]{1,2})H?", text, re.I):
        return match.group(1).zfill(2).upper()
    return ""


def _extract_di(text: str) -> str:
    if match := re.search(r"\bdi\s*:\s*[\"']?([0-9A-Fa-f]{8})", text, re.I):
        return match.group(1).upper()
    if match := re.search(r"\b([A-Fa-f0-9]{2})\s+([A-Fa-f0-9]{2})\s+([A-Fa-f0-9]{2})\s+([A-Fa-f0-9]{2})\b", text):
        return "".join(match.groups()).upper()
    return ""


def _plan_tasks(raw_input: str, context: dict[str, Any]) -> dict[str, Any]:
    has_hex = bool(_extract_hex(raw_input))
    task_intents = context.get("task_intents") or {}
    wants_decode = bool(task_intents.get("decode"))
    wants_build = bool(task_intents.get("build"))
    wants_send = bool(task_intents.get("send")) or bool(re.search(r"通过\s*COM\d+", raw_input, re.I))

    tasks: list[TaskType] = []
    reason: list[str] = []
    if wants_build:
        tasks.append("BUILD")
        reason.append("raw_input indicates build/sync action")
    elif wants_decode or has_hex:
        tasks.append("DECODE")
        reason.append("raw_input asks decode or contains a hex frame")

    if wants_send:
        if not tasks and has_hex:
            tasks.append("SEND")
            reason.append("raw_input contains a complete hex frame and explicit send intent")
        elif tasks:
            tasks.append("SEND")
            reason.append("raw_input contains explicit send/downlink intent")

    if not tasks:
        return {
            "not_supported": True,
            "reason": "Cannot identify BUILD, DECODE, or SEND from raw_input + context.",
        }

    facts = _extract_facts(raw_input)
    facts.update(context.get("facts") or {})
    deterministic_fields = dict(context.get("deterministic_fields") or {})
    if deterministic_fields:
        facts.setdefault("fields", {}).update(deterministic_fields)
    plan = TaskPlan(
        tasks=tasks,
        pending=[_task_label(task) for task in tasks],
        dependencies=_dependencies(tasks),
    )
    return {
        "plan": plan,
        "facts": facts,
        "log": {"task_types": tasks, "reason": reason, "facts": facts},
    }


def _execute_until_blocked(record: RunRecord) -> None:
    while record.task_plan.current_index < len(record.task_plan.tasks):
        task = record.task_plan.tasks[record.task_plan.current_index]
        if task == "BUILD":
            if not _ensure_protocol(record, required=True):
                return
            if not _ensure_build_route(record):
                return
            build_result = _execute_build(record)
            if not build_result:
                return
            if not _execute_decode_verify(record):
                return
            _complete_task(record, "BUILD")
            continue
        if task == "DECODE":
            if not _ensure_decode_frame(record):
                return
            if not _ensure_protocol(record, required=False):
                return
            if not _execute_decode(record, verify=False):
                return
            _complete_task(record, "DECODE")
            continue
        if task == "SEND":
            if not _ensure_send_ready(record):
                return
            if not _execute_send(record):
                return
            _complete_task(record, "SEND")
            continue
        record.state = "FAILED"
        record.error = f"unsupported task: {task}"
        return

    record.state = "SUCCEEDED"
    record.error = ""
    _write_json(record, "result", record.results)
    _append_event(record, "succeeded", {"completed": record.task_plan.completed})


def _ensure_protocol(record: RunRecord, *, required: bool) -> bool:
    if record.facts.get("proto"):
        return True
    if not required and record.facts.get("frame_hex"):
        detected = _detect_protocol(record.facts["frame_hex"])
        if detected:
            record.facts["proto"] = detected
            _append_event(record, "protocol_detected", {"proto": detected})
            return True
    if required:
        _wait(record, "proto", "构造报文必须明确协议。", examples=["dlt645", "csg"])
        return False
    _wait(record, "proto", "解析报文协议不唯一或无法识别。", examples=["dlt645", "csg"])
    return False


def _ensure_build_route(record: RunRecord) -> bool:
    proto = str(record.facts.get("proto") or "")
    if proto.startswith("dlt645"):
        if not record.facts.get("func"):
            _wait(record, "func", "DL/T645 构造需要功能码。", examples=["08", "11", "13"])
            return False
        return True
    if proto.startswith("csg"):
        if not record.facts.get("afn"):
            _wait(record, "afn", "CSG 构造需要 AFN。", examples=["03", "04", "0A"])
            return False
        if not record.facts.get("di"):
            _wait(record, "di", "CSG 构造通常需要 DI 或明确路由。", examples=["E8010001"])
            return False
        return True
    _wait(record, "proto", "协议不在当前支持范围。", examples=["dlt645", "csg"])
    return False


def _execute_build(record: RunRecord) -> bool:
    request = _build_request(record.facts)
    record.results["build_request"] = request
    _append_event(record, "build_request", _redact_large(request))
    response = build_handler.handle(request)
    _append_event(record, "build_result", {"summary": _result_summary(response), "result": response})
    if not response.get("success"):
        missing = response.get("detail", {}).get("missing") or []
        if missing:
            first = missing[0]
            _wait(record, str(first.get("key") or "field"), first.get("desc") or "构造报文缺少必要字段。", examples=first.get("examples") or [])
        else:
            record.state = "FAILED"
            record.error = str(response.get("error") or "build failed")
            _append_event(record, "failed", {"task": "BUILD", "error": record.error, "result": response})
        return False
    data = dict(response.get("data") or {})
    record.results["build"] = data
    record.facts["frame_hex"] = data.get("frame")
    return True


def _execute_decode_verify(record: RunRecord) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_verify_result", {"summary": _result_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = f"BUILD verification decode failed: {response.get('error')}"
        record.results["decode_verify"] = response
        _append_event(record, "failed", {"task": "DECODE_VERIFY", "error": record.error, "result": response})
        return False
    data = dict(response.get("data") or {})
    build = dict(record.results.get("build") or {})
    build_request = dict(record.results.get("build_request") or {})
    check = _verify_build_against_decode(build, data, build_request, record.context)
    differences = check["differences"]
    record.results["decode_verify"] = {"decode": data, "differences": differences, "checked_fields": check["checked_fields"]}
    _append_event(record, "decode_verify_checked", check)
    if differences:
        record.state = "FAILED"
        record.error = "BUILD verification failed"
        _append_event(record, "decode_verify_failed", {"differences": differences})
        return False
    return True


def _execute_decode(record: RunRecord, *, verify: bool) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_result", {"summary": _result_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "decode failed")
        _append_event(record, "failed", {"task": "DECODE", "error": record.error, "result": response})
        return False
    record.results["decode"] = response.get("data") or {}
    return True


def _decode_response(record: RunRecord) -> dict[str, Any]:
    request = {"proto": record.facts.get("proto"), "hex": record.facts.get("frame_hex")}
    _append_event(record, "decode_request", _redact_large(request))
    return decode_handler.handle(request)


def _ensure_decode_frame(record: RunRecord) -> bool:
    if record.facts.get("frame_hex"):
        return True
    _wait(record, "hex", "解析需要完整 HEX 报文。", examples=["68 ... 16"])
    return False


def _ensure_send_ready(record: RunRecord) -> bool:
    if not record.facts.get("frame_hex"):
        _wait(record, "hex", "发送需要完整 HEX 报文或成功构造的 frame_hex。", examples=["AA 55"])
        return False
    if not record.facts.get("port") and not record.facts.get("name"):
        _wait(record, "name", "发送需要明确连接名或串口号。", examples=["cco", "COM9", "mock://loop"])
        return False
    if record.facts.get("name") and not get_connection(str(record.facts["name"])):
        _wait(record, "name", f"串口连接不存在或不可用: {record.facts['name']}", examples=["/serial connect --name cco --port COM9"])
        return False
    return True


def _execute_send(record: RunRecord) -> bool:
    args: dict[str, Any] = {"hex": record.facts["frame_hex"]}
    if record.facts.get("name"):
        args["name"] = record.facts["name"]
    elif record.facts.get("port"):
        generated_name = f"run_{record.run_id[:8]}"
        from wireforge_serial.api import serial_open
        open_args = {
            "name": generated_name,
            "port": record.facts["port"],
            "baudrate": record.facts.get("baudrate", 9600),
        }
        open_result = serial_open(open_args)
        open_result_data = open_result.to_dict()
        _append_event(record, "send_open_result", {"summary": _result_summary(open_result_data), "result": open_result_data})
        if not open_result.success:
            record.state = "FAILED"
            record.error = open_result.error
            _append_event(record, "failed", {"task": "SEND_OPEN", "error": record.error, "result": open_result_data})
            return False
        args["name"] = generated_name
    _append_event(record, "send_request", _redact_large(args))
    response = serial_send(args).to_dict()
    _append_event(record, "send_result", {"summary": _result_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "send failed")
        record.results["send"] = response
        _append_event(record, "failed", {"task": "SEND", "error": record.error, "result": response})
        return False
    record.results["send"] = response.get("data") or {}
    return True


def _complete_task(record: RunRecord, task: TaskType) -> None:
    label = _task_label(task)
    record.task_plan.completed.append(label)
    record.task_plan.current_index += 1
    record.task_plan.pending = [_task_label(t) for t in record.task_plan.tasks[record.task_plan.current_index:]]
    _append_event(record, "task_completed", {"task": label})


def _build_request(facts: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "proto", "func", "afn", "di", "dir", "direction", "address", "preamble",
        "seq", "addr", "has_address", "intent",
    }
    request = {key: value for key, value in facts.items() if key in allowed and value not in ("", None)}
    for key, value in facts.get("fields", {}).items():
        request[key] = value
    return request


def _verify_build_against_decode(
    build: dict[str, Any],
    decode: dict[str, Any],
    build_request: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    differences: list[str] = []
    checked_fields: list[dict[str, Any]] = []
    if build.get("protocol") and decode.get("protocol") and build["protocol"] != decode["protocol"]:
        differences.append(f"protocol mismatch: build={build['protocol']} decode={decode['protocol']}")
    message_id = str((build.get("resolved") or {}).get("message_id") or "")
    if message_id and decode.get("path") and message_id not in str(decode["path"]):
        differences.append(f"route mismatch: build={build.get('path')} decode={decode['path']}")
    value_aliases = context.get("value_aliases") or {}
    for field, expected in _verifiable_build_fields(build_request).items():
        actual = _find_decoded_field(decode, field)
        ok = _values_match(field, expected, actual, value_aliases)
        checked_fields.append({
            "field": field,
            "expected": expected,
            "actual": actual,
            "ok": ok,
        })
        if not ok:
            differences.append(f"field mismatch: {field} expected={expected} decode={actual}")
    return {"differences": differences, "checked_fields": checked_fields}


def _verifiable_build_fields(build_request: dict[str, Any]) -> dict[str, Any]:
    skipped = {"proto", "protocol", "intent", "name", "port", "baudrate", "timeout"}
    return {
        str(key): value
        for key, value in build_request.items()
        if key not in skipped and value not in ("", None)
    }


def _values_match(field: str, expected: Any, actual: Any, aliases: dict[str, Any]) -> bool:
    if actual is None:
        return False
    normalized_actual = _normalize_compare_value(actual)
    normalized_expected = _normalize_compare_value(expected)
    field_aliases = aliases.get(field) if isinstance(aliases, dict) else None
    if isinstance(field_aliases, dict) and str(expected) in field_aliases:
        return normalized_actual in {_normalize_compare_value(item) for item in field_aliases[str(expected)]}
    return normalized_actual == normalized_expected


def _normalize_compare_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"0x[0-9a-fA-F]+", compact):
        return str(int(compact, 16))
    if re.fullmatch(r"[0-9A-Fa-f]{2}", compact):
        return str(int(compact, 16))
    return compact.lower()


def _find_decoded_field(decode: dict[str, Any], field: str) -> Any:
    values = decode.get("values")
    if not isinstance(values, dict):
        return None
    found: Any = None

    def visit(value: Any, key: str = "") -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if str(child_key).split(".")[-1] == field:
                    found = child_value
                    return
                visit(child_value, str(child_key))

    visit(values)
    return found


def _detect_protocol(frame_hex: str) -> str:
    clean = re.sub(r"\s+", "", frame_hex).upper()
    if clean.startswith("FE"):
        clean_no_fe = clean.lstrip("FE")
    else:
        clean_no_fe = clean
    if clean_no_fe.startswith("68") and len(clean_no_fe) >= 24:
        if len(clean_no_fe) >= 24 and clean_no_fe[14:16] == "68":
            return "dlt645"
        return "csg"
    return ""


def _extract_facts(raw_input: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if match := re.search(r"\bCOM\d+\b", raw_input, re.IGNORECASE):
        facts["port"] = match.group(0).upper()
    if match := re.search(r"(?:--name|连接名|name)\s*[=: ]\s*([A-Za-z_][A-Za-z0-9_-]*)", raw_input):
        facts["name"] = match.group(1)
    if match := re.search(r"(?:func|功能码)\s*[=: ]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]{2})", raw_input):
        facts["func"] = match.group(1)
    if match := re.search(r"\bAFN\s*[=: ]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]{2})", raw_input, re.IGNORECASE):
        facts["afn"] = match.group(1)
    if match := re.search(r"\bDI\s*[=: ]\s*([0-9a-fA-F]{8})", raw_input, re.IGNORECASE):
        facts["di"] = match.group(1).upper()
    if match := re.search(r"(?:address|地址)\s*[=: ]\s*([0-9A-Fa-f]{12}|A{12})", raw_input):
        facts["address"] = match.group(1).upper()
    if frame := _extract_hex(raw_input):
        facts["frame_hex"] = frame
    return facts


def _extract_hex(raw_input: str) -> str:
    candidates = re.findall(r"(?:[0-9A-Fa-f]{2}[\s,;:-]*){4,}", raw_input)
    if not candidates:
        return ""
    best = max(candidates, key=len)
    clean = re.sub(r"[^0-9A-Fa-f]", "", best)
    return " ".join(clean[i:i + 2].upper() for i in range(0, len(clean), 2))


def _normalize_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(user_input)
    if "protocol" in normalized and "proto" not in normalized:
        normalized["proto"] = normalized.pop("protocol")
    if "hex" in normalized and "frame_hex" not in normalized:
        normalized["frame_hex"] = normalized.pop("hex")
    return normalized


def _wait(record: RunRecord, field: str, message: str, examples: list[Any] | None = None) -> None:
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": field,
        "message": message,
        "examples": examples or [],
    }
    _append_event(record, "waiting_input", record.waiting_input)


def _dependencies(tasks: list[TaskType]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {}
    if "SEND" in tasks and "BUILD" in tasks:
        deps["SEND"] = ["BUILD", "DECODE_VERIFY"]
    if "SEND" in tasks and "DECODE" in tasks:
        deps["SEND"] = ["DECODE"]
    return deps


def _task_label(task: TaskType) -> str:
    if task == "BUILD":
        return "BUILD+DECODE_VERIFY"
    return task


def _load_or_create(run_id: str | None, raw_input: str | None) -> RunRecord:
    rid = run_id or uuid.uuid4().hex
    path = _run_dir(rid) / "state.json"
    if path.exists():
        return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if not raw_input:
        raise ValueError("raw_input is required for a new run")
    record = RunRecord(run_id=rid, raw_input=raw_input)
    _run_dir(rid).mkdir(parents=True, exist_ok=True)
    _write_text(record, "raw_input", raw_input)
    return record


def _save(record: RunRecord) -> None:
    _run_dir(record.run_id).mkdir(parents=True, exist_ok=True)
    _write_json(record, "state", record.to_dict())


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def _write_json(record: RunRecord, name: str, data: Any) -> None:
    path = _run_dir(record.run_id) / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(record: RunRecord, name: str, text: str) -> None:
    path = _run_dir(record.run_id) / name
    path.write_text(text, encoding="utf-8")


def _append_event(record: RunRecord, event: str, data: dict[str, Any]) -> None:
    _run_dir(record.run_id).mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": record.run_id,
        "state": record.state,
        "event": event,
        "data": data,
    }
    with (_run_dir(record.run_id) / "events").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    _append_workflow_log(record, event, data, payload["timestamp"])


def _append_workflow_log(record: RunRecord, event: str, data: dict[str, Any], timestamp: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WORKFLOW_LOG.open("a", encoding="utf-8") as f:
        f.write(_format_workflow_log(record, event, data, timestamp))


def _format_workflow_log(record: RunRecord, event: str, data: dict[str, Any], timestamp: str) -> str:
    lines = [
        f"[{timestamp}] run={record.run_id} state={record.state} step={event}",
    ]
    if event == "enter":
        lines.extend([
            f"raw_input: {record.raw_input}",
            f"user_input: {_format_inline(data.get('user_input') or {})}",
        ])
    elif event == "context_ready":
        lines.extend([
            f"context.provider: {record.context.get('provider') or ''}",
            f"context.summary: {record.context.get('summary') or ''}",
            "context.sources:",
            *_format_list(record.context.get("sources") or []),
        ])
        deterministic_fields = record.context.get("deterministic_fields") or {}
        if deterministic_fields:
            lines.append(f"context.deterministic_fields: {_format_inline(deterministic_fields)}")
        hints = record.context.get("hints") or []
        if hints:
            lines.extend(["context.hints:", *_format_list([_format_inline(hint) for hint in hints])])
    elif event == "plan_ready":
        lines.extend([
            f"task_types: {', '.join(record.task_plan.tasks)}",
            f"task_plan: {_format_task_plan(record.task_plan)}",
            f"facts: {_format_inline(data.get('facts') or record.facts)}",
        ])
        if data.get("reason"):
            lines.extend(["reason:", *_format_list(data["reason"])])
    elif event.endswith("_request"):
        lines.extend([
            "request:",
            *_format_mapping(data),
        ])
    elif event.endswith("_result") or event == "send_open_result":
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else _result_summary(result)
        lines.extend([
            f"success: {summary.get('success')}",
            f"error: {summary.get('error') or ''}",
        ])
        result_data = result.get("data") if isinstance(result, dict) else {}
        if isinstance(result_data, dict):
            if result_data.get("frame"):
                lines.append(f"frame: {result_data['frame']}")
            if result_data.get("path"):
                lines.append(f"path: {result_data['path']}")
            resolved = result_data.get("resolved")
            if resolved:
                lines.append(f"resolved: {_format_inline(resolved)}")
            decoded_fields = _format_decoded_fields(result_data)
            if decoded_fields:
                lines.extend(["decoded_fields:", *decoded_fields])
    elif event == "decode_verify_checked":
        checked_fields = data.get("checked_fields") or []
        if checked_fields:
            lines.append("checked_fields:")
            for item in checked_fields:
                lines.append(
                    "  - "
                    f"{item.get('field')}: "
                    f"expected={item.get('expected')} "
                    f"actual={item.get('actual')} "
                    f"ok={item.get('ok')}"
                )
        else:
            lines.append("checked_fields: none")
        differences = data.get("differences") or []
        if differences:
            lines.extend(["differences:", *_format_list(differences)])
        else:
            lines.append("differences: none")
    elif event == "waiting_input":
        lines.extend([
            f"field: {data.get('field') or ''}",
            f"message: {data.get('message') or ''}",
            f"examples: {_format_inline(data.get('examples') or [])}",
        ])
    elif event in {"failed", "failed_exception", "decode_verify_failed", "not_supported"}:
        lines.extend([
            f"error: {data.get('error') or record.error or data.get('reason') or ''}",
            f"detail: {_format_inline(data)}",
        ])
    elif event == "task_completed":
        lines.append(f"completed: {data.get('task') or ''}")
    elif event == "succeeded":
        lines.append(f"completed: {_format_inline(data.get('completed') or [])}")
    elif event == "round_exit":
        lines.extend([
            f"final_state: {data.get('final_state') or record.state}",
            f"error: {data.get('error') or ''}",
        ])
        final_result = data.get("final_result") if isinstance(data.get("final_result"), dict) else {}
        build = final_result.get("build") if isinstance(final_result, dict) else None
        if isinstance(build, dict):
            if build.get("frame"):
                lines.append(f"final_frame: {build['frame']}")
            if build.get("path"):
                lines.append(f"final_path: {build['path']}")
        waiting = data.get("waiting_input")
        if waiting:
            lines.append(f"waiting_input: {_format_inline(waiting)}")
    else:
        lines.extend(["data:", *_format_mapping(data)])
    return "\n".join(lines) + "\n\n"


def _format_task_plan(plan: TaskPlan) -> str:
    return (
        f"tasks=[{', '.join(plan.tasks)}], "
        f"completed=[{', '.join(plan.completed)}], "
        f"pending=[{', '.join(plan.pending)}]"
    )


def _format_mapping(data: dict[str, Any]) -> list[str]:
    return [f"  {key}: {_format_inline(value)}" for key, value in data.items()]


def _format_list(items: list[Any]) -> list[str]:
    return [f"  - {_format_inline(item)}" for item in items]


def _format_inline(value: Any) -> str:
    compact = _compact_log_value(value, max_string=500, max_items=20)
    if isinstance(compact, (dict, list)):
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    return str(compact)


def _format_decoded_fields(result_data: dict[str, Any]) -> list[str]:
    values = result_data.get("values")
    if not isinstance(values, dict):
        return []
    return [
        f"  - {path}: {value}"
        for path, value in _flatten_scalar_fields(values, max_items=20)
    ]


def _flatten_scalar_fields(value: Any, *, max_items: int, prefix: str = "") -> list[tuple[str, Any]]:
    if max_items <= 0:
        return []
    if isinstance(value, dict):
        fields: list[tuple[str, Any]] = []
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(_flatten_scalar_fields(child, max_items=max_items - len(fields), prefix=child_prefix))
            if len(fields) >= max_items:
                break
        return fields
    if isinstance(value, list):
        fields = []
        for index, child in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            fields.extend(_flatten_scalar_fields(child, max_items=max_items - len(fields), prefix=child_prefix))
            if len(fields) >= max_items:
                break
        return fields
    return [(prefix, value)]


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": context.get("provider"),
        "sources": context.get("sources", [])[:5],
        "summary": context.get("summary", ""),
    }


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") or {}
    return {
        "success": result.get("success"),
        "status": result.get("status"),
        "error": result.get("error"),
        "keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "frame": data.get("frame") if isinstance(data, dict) else None,
    }


def _redact_large(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for key, value in list(out.items()):
        if isinstance(value, str) and len(value) > 160:
            out[key] = value[:160] + "..."
    return out


def _compact_log_value(value: Any, *, max_string: int = 4000, max_items: int = 100) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        compacted = {str(k): _compact_log_value(v, max_string=max_string, max_items=max_items) for k, v in items[:max_items]}
        if len(items) > max_items:
            compacted["__truncated_keys__"] = len(items) - max_items
        return compacted
    if isinstance(value, list):
        compacted_list = [_compact_log_value(v, max_string=max_string, max_items=max_items) for v in value[:max_items]]
        if len(value) > max_items:
            compacted_list.append({"__truncated_items__": len(value) - max_items})
        return compacted_list
    if isinstance(value, tuple):
        return _compact_log_value(list(value), max_string=max_string, max_items=max_items)
    if isinstance(value, str) and len(value) > max_string:
        return value[:max_string] + f"...<truncated {len(value) - max_string} chars>"
    return value
