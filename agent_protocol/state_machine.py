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
from wireforge_serial.api import get_connection, serial_send


ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "agent_protocol_runs"

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
    }


def _advance(record: RunRecord) -> None:
    if record.state == "INIT":
        record.context = MarkdownContextProvider().build_context(record.raw_input)
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


class MarkdownContextProvider:
    """Read local markdown/protocol files and produce a stable context shape."""

    def __init__(self, root: Path = ROOT):
        self.root = root

    def build_context(self, raw_input: str) -> dict[str, Any]:
        text = raw_input.lower()
        sources: list[str] = []
        hints: list[dict[str, Any]] = []

        readme = self.root / "README.md"
        if readme.exists():
            sources.append(str(readme))

        protocol_root = self.root / "protocol_tool" / "protocols"
        if protocol_root.exists():
            sources.append(str(protocol_root / "registry.yaml"))

        if any(word in text for word in ["同步", "校时", "时钟", "time", "clock"]):
            hints.append({
                "kind": "capability",
                "summary": "用户可能需要构造时间同步/校时报文；必须由明确协议和路由确认后才能构造。",
                "fields": ["proto", "route", "time", "address"],
                "certainty": "candidate",
            })
        if re.search(r"\bCOM\d+\b", raw_input, re.IGNORECASE):
            hints.append({
                "kind": "serial",
                "summary": "用户输入中包含串口号。",
                "fields": ["port"],
                "certainty": "explicit",
            })

        return {
            "provider": "MarkdownContextProvider",
            "sources": sources,
            "summary": "; ".join(item["summary"] for item in hints) or "未找到明确协议任务上下文。",
            "hints": hints,
        }


def _plan_tasks(raw_input: str, context: dict[str, Any]) -> dict[str, Any]:
    text = raw_input.lower()
    has_hex = bool(_extract_hex(raw_input))
    wants_decode = any(word in text for word in ["解析", "decode"])
    wants_build = any(word in text for word in ["构造", "生成", "组帧", "build", "同步", "校时", "时钟", "clock"])
    wants_send = any(word in text for word in ["发送", "下发", "写入", "执行", "send"]) or bool(re.search(r"通过\s*COM\d+", raw_input, re.I))

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
    _append_event(record, "build_request", _redact_large(request))
    response = build_handler.handle(request)
    _append_event(record, "build_result", _result_summary(response))
    if not response.get("success"):
        missing = response.get("detail", {}).get("missing") or []
        if missing:
            first = missing[0]
            _wait(record, str(first.get("key") or "field"), first.get("desc") or "构造报文缺少必要字段。", examples=first.get("examples") or [])
        else:
            record.state = "FAILED"
            record.error = str(response.get("error") or "build failed")
        return False
    data = dict(response.get("data") or {})
    record.results["build"] = data
    record.facts["frame_hex"] = data.get("frame")
    return True


def _execute_decode_verify(record: RunRecord) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_verify_result", _result_summary(response))
    if not response.get("success"):
        record.state = "FAILED"
        record.error = f"BUILD verification decode failed: {response.get('error')}"
        record.results["decode_verify"] = response
        return False
    data = dict(response.get("data") or {})
    build = dict(record.results.get("build") or {})
    differences = _verify_build_against_decode(record.raw_input, build, data)
    record.results["decode_verify"] = {"decode": data, "differences": differences}
    if differences:
        record.state = "FAILED"
        record.error = "BUILD verification failed"
        _append_event(record, "decode_verify_failed", {"differences": differences})
        return False
    return True


def _execute_decode(record: RunRecord, *, verify: bool) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_result", _result_summary(response))
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "decode failed")
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
        _append_event(record, "send_open_result", _result_summary(open_result.to_dict()))
        if not open_result.success:
            record.state = "FAILED"
            record.error = open_result.error
            return False
        args["name"] = generated_name
    _append_event(record, "send_request", _redact_large(args))
    response = serial_send(args).to_dict()
    _append_event(record, "send_result", _result_summary(response))
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "send failed")
        record.results["send"] = response
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


def _verify_build_against_decode(raw_input: str, build: dict[str, Any], decode: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    if build.get("protocol") and decode.get("protocol") and build["protocol"] != decode["protocol"]:
        differences.append(f"protocol mismatch: build={build['protocol']} decode={decode['protocol']}")
    message_id = str((build.get("resolved") or {}).get("message_id") or "")
    if message_id and decode.get("path") and message_id not in str(decode["path"]):
        differences.append(f"route mismatch: build={build.get('path')} decode={decode['path']}")
    text = raw_input.lower()
    path_text = str(decode.get("path", "")).lower()
    if any(word in text for word in ["同步", "校时", "时钟", "clock", "time"]):
        if not any(word in path_text for word in ["time", "clock", "broadcast_time", "write", "set"]):
            differences.append("raw_input asks time sync, but decoded route does not clearly indicate time/write/set")
    return differences


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
    text = raw_input.lower()
    if "dlt645" in text or "645" in text:
        facts["proto"] = "dlt645"
    elif "csg" in text or "南网" in text:
        facts["proto"] = "csg"
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
