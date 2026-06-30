"""Recoverable MCP state machine driven by a deterministic protocol map."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from agent_protocol.protocol_map import BOOTSTRAP_COMMAND, ProtocolMapMissingError, find_entry, load_protocol_map
from console.handlers import build as build_handler
from console.handlers import decode as decode_handler
from console.handlers.route import handle as route_handle
from wireforge_serial.api import get_connection, serial_open, serial_send

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "log" / "agent_protocol_runs"
LOG_DIR = ROOT / "log"
WORKFLOW_LOG = LOG_DIR / "agent_protocol_workflow.log"
MAX_BUILD_RETRIES = 3
DEFAULT_RESPONSE_MAX_RATIO = 20
DEFAULT_RESPONSE_MIN_BYTES = 512

TaskType = Literal["BUILD", "DECODE", "SEND"]
RunState = Literal[
    "INIT",
    "MAP_READY",
    "PROTOCOL_MATCH",
    "ROUTING",
    "WAITING_VALUES",
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
    route_result: dict[str, Any] = field(default_factory=dict)
    build_retries: int = 0
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
            "route_result": self.route_result,
            "build_retries": self.build_retries,
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
            route_result=dict(data.get("route_result") or {}),
            build_retries=int(data.get("build_retries") or 0),
            error=str(data.get("error") or ""),
        )


def run_agent_protocol(
    raw_input: str | None = None,
    *,
    run_id: str | None = None,
    user_input: dict[str, Any] | None = None,
    debug: bool | None = None,
) -> dict[str, Any]:
    debug_enabled = _debug_enabled(debug)
    try:
        record = _load_or_create(run_id, raw_input)
    except Exception as exc:
        record = RunRecord(run_id=run_id or uuid.uuid4().hex, raw_input=raw_input or "", state="FAILED", error=str(exc))
        _append_event(record, "load_failed", {"error": str(exc)})
        _save(record)
        return _public_result(record, debug=debug_enabled)
    _append_event(record, "enter", {"state": record.state, "user_input": user_input or {}})

    if raw_input and not record.raw_input:
        record.raw_input = raw_input
        _write_text(record, "raw_input", record.raw_input)

    if user_input:
        _apply_user_input(record, user_input)

    try:
        _advance(record)
    except Exception as exc:
        record.state = "FAILED"
        record.error = str(exc)
        _append_event(record, "failed_exception", {"error": str(exc)})

    _append_event(record, "round_exit", {
        "mcp_exit_state": record.state,
        "waiting_input": record.waiting_input,
        "error": record.error,
        "results": _result_summary(record.results),
    })
    _save(record)
    return _public_result(record, debug=debug_enabled)


def _apply_user_input(record: RunRecord, user_input: dict[str, Any]) -> None:
    normalized = _normalize_user_input(user_input)
    if _is_waiting_for_protocol_match(record) and "fields" in normalized and not _has_route_input(normalized):
        _wait(
            record,
            "protocol_match",
            "当前仍需先选择协议地图 entry_id 或 route_params，不能直接提交 fields。",
            protocol_map_ref=record.context.get("protocol_map_ref") if isinstance(record.context.get("protocol_map_ref"), dict) else None,
            candidates=record.waiting_input.get("candidates") if isinstance(record.waiting_input.get("candidates"), list) else None,
        )
        _append_event(record, "mcp_reject_out_of_order_fields", {
            "reason": "fields supplied before protocol_match",
            "user_input_keys": sorted(normalized.keys()),
        })
        return
    if entry_id := normalized.get("entry_id"):
        try:
            entry = find_entry(_full_protocol_map(), str(entry_id))
        except (ProtocolMapMissingError, ValueError) as exc:
            record.state = "FAILED"
            record.error = str(exc)
            _append_event(record, "protocol_match_failed", {"entry_id": entry_id, "error": record.error})
            return
        if not entry:
            record.state = "FAILED"
            record.error = f"protocol map entry not found: {entry_id}"
            return
        normalized.setdefault("route_params", entry.get("route_params") or {})
        record.results["protocol_match"] = entry

    route_params = dict(normalized.get("route_params") or {})
    for key in ("proto", "func", "afn", "di", "dir", "has_address"):
        if key in normalized and key not in route_params:
            route_params[key] = normalized[key]
    if route_params:
        record.facts.update(route_params)
        if record.state != "INIT":
            record.state = "PROTOCOL_MATCH"
            record.waiting_input = {}

    if "fields" in normalized:
        record.facts["fields"] = dict(normalized.get("fields") or {})
        if record.state != "INIT":
            record.state = "WAITING_VALUES"
            record.waiting_input = {}

    if "from_frame_hex" in normalized:
        record.facts["from_frame_hex"] = str(normalized["from_frame_hex"]).strip()
        record.facts["build_mode"] = "from_frame"

    if "frame_hex" in normalized:
        record.facts["frame_hex"] = normalized["frame_hex"]

    if "name" in normalized:
        record.facts["name"] = normalized["name"]
    if "port" in normalized:
        record.facts["port"] = normalized["port"]


def _advance(record: RunRecord) -> None:
    if record.state == "INIT":
        _initialize_run(record)

    if record.state == "PROTOCOL_MATCH":
        record.state = "ROUTING"

    if record.state == "ROUTING":
        if not _execute_route(record):
            return
        record.state = "WAITING_VALUES"
        _wait_for_values(record)
        return

    if record.state == "WAITING_VALUES":
        if not _ensure_values(record):
            return
        record.state = "EXECUTING"

    if record.state == "EXECUTING":
        _execute_until_blocked(record)


def _initialize_run(record: RunRecord) -> None:
    tasks = _detect_tasks(record.raw_input)
    if not tasks:
        record.state = "FAILED"
        record.error = "NOT_SUPPORTED"
        record.results["reason"] = "Cannot identify BUILD, DECODE, or SEND."
        _append_event(record, "not_supported", {"raw_input": record.raw_input})
        return

    record.task_plan = TaskPlan(
        tasks=tasks,
        pending=[_task_label(task) for task in tasks],
        dependencies=_dependencies(tasks),
    )
    _write_json(record, "task_plan", record.task_plan.to_dict())

    if "DECODE" in tasks and "BUILD" not in tasks:
        frame_hex = _extract_hex(record.raw_input)
        if frame_hex:
            record.facts["frame_hex"] = frame_hex
            record.state = "EXECUTING"
            _append_event(record, "decode_ready", {"frame_hex": frame_hex})
            return
        _wait(record, "hex", "解析需要完整 HEX 报文。", examples=["FE FE 68 ... 16"])
        return

    if "BUILD" in tasks and _is_from_frame_build(record.raw_input, tasks, record.facts):
        _initialize_from_frame_build(record)
        return

    try:
        protocol_map = _full_protocol_map()
    except ProtocolMapMissingError as exc:
        record.state = "FAILED"
        record.error = str(exc)
        record.results["bootstrap"] = {
            "required": True,
            "command": BOOTSTRAP_COMMAND,
        }
        _append_event(record, "protocol_map_missing", {
            "error": record.error,
            "bootstrap_command": BOOTSTRAP_COMMAND,
        })
        return
    record.context = {
        "provider": "ProtocolMap",
        "protocol_map_ref": _protocol_map_ref(protocol_map),
    }
    _write_json(record, "protocol_map", protocol_map)
    _append_event(record, "map_ready", {
        "protocols": list((protocol_map.get("protocols") or {}).keys()),
        "entries": _map_entry_count(protocol_map),
    })
    _wait(
        record,
        "protocol_match",
        "请从候选报文中选择唯一 entry_id；若候选不匹配，提示用户补充协议地图描述。",
        protocol_map_ref=_protocol_map_ref(protocol_map),
        candidates=_candidate_entries(protocol_map, record.raw_input),
    )


def _execute_route(record: RunRecord) -> bool:
    route_args = _route_args(record.facts)
    record.results["route_request"] = dict(route_args)
    _append_event(record, "route_request", route_args)
    response = route_handle(route_args)
    _append_event(record, "route_result", {"summary": _handler_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = f"route failed: {response.get('error')}"
        _append_event(record, "failed", {"task": "ROUTE", "error": record.error})
        return False
    record.route_result = dict(response.get("data") or {})
    record.results["route"] = record.route_result
    _write_json(record, "route", record.route_result)
    return True


def _wait_for_values(record: RunRecord) -> None:
    schema = list(record.route_result.get("input_schema") or [])
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": "values",
        "message": "请按 input_schema 填充 fields；缺失值需要询问用户。",
        "route_params": _route_args(record.facts),
        "route": record.route_result,
        "input_schema": schema,
        "required_fields": _required_schema_fields(schema),
    }
    _append_event(record, "mcp_exit_waiting_values", record.waiting_input)


def _wait_for_from_frame_values(record: RunRecord) -> None:
    schema = list(record.route_result.get("input_schema") or [])
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": "values",
        "source_mode": "from_frame",
        "message": "基于源报文构造；fields 仅填需覆盖的字段，原样重建传 {}。",
        "from_frame_hex": record.facts.get("from_frame_hex"),
        "route_params": _route_args(record.facts),
        "route": record.route_result,
        "input_schema": schema,
        "decoded_values": dict(record.facts.get("decoded_values") or {}),
        "required_fields": [],
    }
    _append_event(record, "mcp_exit_from_frame_values", record.waiting_input)


def _initialize_from_frame_build(record: RunRecord) -> None:
    from console.build_resolver import decode_frame, resolve
    from console.handlers.build import _flatten_values

    hex_text = _source_frame_hex(record)
    if not hex_text:
        record.state = "FAILED"
        record.error = "from_frame build requires source hex in raw_input or user_input.from_frame"
        _append_event(record, "from_frame_missing_hex", {})
        return

    user_proto = str(record.facts.get("proto") or "").strip()
    try:
        decoded = decode_frame(hex_text, proto=user_proto or None)
    except Exception as exc:
        record.state = "FAILED"
        record.error = f"from_frame decode failed: {exc}"
        _append_event(record, "from_frame_decode_failed", {"error": str(exc)})
        return

    target_info = dict(decoded.get("target_info") or {})
    _append_event(record, "from_frame_decode", {
        "target_info": target_info,
        "path": decoded.get("path"),
    })

    try:
        target = resolve(target_info)
    except Exception as exc:
        record.state = "FAILED"
        record.error = f"from_frame resolve failed: {exc}"
        _append_event(record, "from_frame_resolve_failed", {"error": str(exc)})
        return

    record.facts["from_frame_hex"] = decoded["frame_hex"]
    record.facts["build_mode"] = "from_frame"
    record.facts["decoded_values"] = _flatten_values(decoded["values"])

    route_dict = target.to_dict()
    record.route_result = route_dict
    record.results["from_frame"] = {"decoded": decoded, "route": route_dict}
    _write_json(record, "route", route_dict)

    ti = target.target_info
    for key in ("proto", "func", "afn", "di", "dir", "has_address"):
        if key in ti and ti[key] not in ("", None):
            val = ti[key]
            if key == "proto":
                val = "dlt645" if "dlt645" in str(val) else "csg" if "csg" in str(val) else val
            record.facts[key] = val

    record.context = {"provider": "FromFrame", "build_mode": "from_frame"}
    _append_event(record, "from_frame_ready", {
        "from_frame_hex": record.facts["from_frame_hex"],
        "variant_id": route_dict.get("variant_id"),
    })
    if "fields" in record.facts:
        record.state = "WAITING_VALUES"
        record.waiting_input = {}
    else:
        _wait_for_from_frame_values(record)


def _is_from_frame_mode(record: RunRecord) -> bool:
    return record.facts.get("build_mode") == "from_frame"


def _ensure_values(record: RunRecord) -> bool:
    if _is_from_frame_mode(record):
        if "fields" not in record.facts:
            _wait_for_from_frame_values(record)
            return False
        return True

    schema = list(record.route_result.get("input_schema") or [])
    required = _required_schema_fields(schema)
    fields = dict(record.facts.get("fields") or {})
    missing = [field for field in required if field not in fields]
    if missing:
        record.state = "WAITING_INPUT"
        record.waiting_input = {
            "field": "values",
            "message": "构造报文缺少必要字段值。",
            "missing_fields": missing,
            "input_schema": schema,
            "route": record.route_result,
        }
        _append_event(record, "mcp_exit_missing_values", record.waiting_input)
        return False
    return True


def _execute_until_blocked(record: RunRecord) -> None:
    while record.task_plan.current_index < len(record.task_plan.tasks):
        task = record.task_plan.tasks[record.task_plan.current_index]
        if task == "BUILD":
            if not _execute_build(record):
                return
            if not _execute_decode_verify(record):
                return
            _complete_task(record, "BUILD")
            continue
        if task == "DECODE":
            if not _ensure_decode_frame(record):
                return
            if not _ensure_protocol_for_decode(record):
                return
            if not _execute_decode(record):
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


def _execute_build(record: RunRecord) -> bool:
    request = _build_request(record.facts)
    record.results["build_request"] = request
    event = "from_frame_build_request" if record.facts.get("build_mode") == "from_frame" else "build_request"
    _append_event(record, event, request)
    response = build_handler.handle(request)
    _append_event(record, "build_result", {"summary": _handler_summary(response), "result": response})
    if not response.get("success"):
        record.build_retries += 1
        if record.build_retries >= MAX_BUILD_RETRIES:
            record.state = "FAILED"
            record.error = f"build failed after {MAX_BUILD_RETRIES} attempts: {response.get('error')}"
            record.results["build_error"] = response
            _append_event(record, "failed", {"task": "BUILD", "error": record.error, "attempt": record.build_retries})
            return False
        record.state = "WAITING_INPUT"
        record.waiting_input = {
            "field": "values",
            "message": "build 失败，请 Agent 根据错误重新构造 fields。",
            "attempt": record.build_retries,
            "max_attempts": MAX_BUILD_RETRIES,
            "error": response.get("error"),
            "result": response,
            "input_schema": record.route_result.get("input_schema") or [],
            "route": record.route_result,
        }
        _append_event(record, "mcp_exit_build_retry", record.waiting_input)
        return False
    data = dict(response.get("data") or {})
    record.results["build"] = data
    record.facts["frame_hex"] = data.get("frame")
    record.build_retries = 0
    return True


def _execute_decode_verify(record: RunRecord) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_verify_result", {"summary": _handler_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = f"BUILD verification decode failed: {response.get('error')}"
        record.results["decode_verify"] = response
        return False
    data = dict(response.get("data") or {})
    check = _verify_build_against_decode(
        data,
        dict(record.results.get("build_request") or {}),
        list(record.route_result.get("input_schema") or []),
    )
    record.results["decode_verify"] = {
        "decode": data,
        "differences": check["differences"],
        "checked_fields": check["checked_fields"],
    }
    _append_event(record, "decode_verify_checked", check)
    if check["differences"]:
        record.state = "FAILED"
        record.error = "BUILD verification failed"
        _append_event(record, "decode_verify_failed", check)
        return False
    return True


def _execute_decode(record: RunRecord) -> bool:
    response = _decode_response(record)
    _append_event(record, "decode_result", {"summary": _handler_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "decode failed")
        return False
    record.results["decode"] = response.get("data") or {}
    return True


def _execute_send(record: RunRecord) -> bool:
    args = {"hex": record.facts["frame_hex"]}
    if record.facts.get("name"):
        args["name"] = record.facts["name"]
    elif record.facts.get("port"):
        generated_name = f"run_{record.run_id[:8]}"
        open_result = serial_open({"name": generated_name, "port": record.facts["port"]})
        _append_event(record, "send_open_result", {"summary": _handler_summary(open_result.to_dict()), "result": open_result.to_dict()})
        if not open_result.success:
            record.state = "FAILED"
            record.error = open_result.error
            return False
        args["name"] = generated_name
    _append_event(record, "send_request", args)
    response = serial_send(args).to_dict()
    _append_event(record, "send_result", {"summary": _handler_summary(response), "result": response})
    if not response.get("success"):
        record.state = "FAILED"
        record.error = str(response.get("error") or "send failed")
        record.results["send"] = response
        return False
    record.results["send"] = response.get("data") or {}
    return True


def _decode_response(record: RunRecord) -> dict[str, Any]:
    request = {"proto": record.facts.get("proto"), "hex": record.facts.get("frame_hex")}
    _append_event(record, "decode_request", request)
    return decode_handler.handle(request)


def _build_request(facts: dict[str, Any]) -> dict[str, Any]:
    if facts.get("build_mode") == "from_frame":
        request: dict[str, Any] = {"from_frame": facts["from_frame_hex"]}
        request.update(dict(facts.get("fields") or {}))
        for key in ("address", "preamble", "seq", "addr", "name", "port", "proto"):
            if key in facts and facts[key] not in ("", None):
                request[key] = facts[key]
        return request

    request = _route_args(facts)
    for key, value in dict(facts.get("fields") or {}).items():
        request[key] = value
    for key in ("address", "preamble", "seq", "addr", "name", "port"):
        if key in facts and facts[key] not in ("", None):
            request[key] = facts[key]
    return request


def _route_args(facts: dict[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for key in ("proto", "func", "afn", "di", "dir", "has_address"):
        if key in facts and facts[key] not in ("", None):
            args[key] = facts[key]
    return args


def _required_schema_fields(schema: list[dict[str, Any]]) -> list[str]:
    return [
        str(field["name"])
        for field in schema
        if field.get("default") in (None, "")
    ]


def _ensure_decode_frame(record: RunRecord) -> bool:
    if record.facts.get("frame_hex"):
        return True
    _wait(record, "hex", "解析需要完整 HEX 报文。", examples=["FE FE 68 ... 16"])
    return False


def _ensure_protocol_for_decode(record: RunRecord) -> bool:
    if record.facts.get("proto"):
        return True
    detected = _detect_protocol(record.facts.get("frame_hex", ""))
    if detected:
        record.facts["proto"] = detected
        _append_event(record, "protocol_detected", {"proto": detected})
        return True
    _wait(record, "proto", "解析报文协议不唯一或无法识别。", examples=["dlt645", "csg"])
    return False


def _ensure_send_ready(record: RunRecord) -> bool:
    if not record.facts.get("frame_hex"):
        _wait(record, "hex", "发送需要完整 HEX 报文或成功构造的 frame_hex。", examples=["AA 55"])
        return False
    if not record.facts.get("port") and not record.facts.get("name"):
        _wait(record, "name", "发送需要明确连接名或串口号。", examples=["cco", "COM9", "mock://loop"])
        return False
    if record.facts.get("name") and not get_connection(str(record.facts["name"])):
        _wait(record, "name", f"串口连接不存在: {record.facts['name']}", examples=["/serial connect --name cco --port COM9"])
        return False
    return True


def _verify_build_against_decode(
    decode: dict[str, Any],
    build_request: dict[str, Any],
    input_schema: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    differences: list[str] = []
    checked_fields: list[dict[str, Any]] = []
    values = decode.get("values") if isinstance(decode.get("values"), dict) else {}
    schema_by_name = {
        str(item.get("name")): item
        for item in (input_schema or [])
        if isinstance(item, dict) and item.get("name")
    }
    for field, expected in _verifiable_build_fields(build_request).items():
        actual = _find_decoded_field(values, field)
        schema = schema_by_name.get(field)
        ok = _values_match(expected, actual, schema)
        checked = {"field": field, "expected": expected, "actual": actual, "ok": ok}
        if schema and schema.get("type"):
            checked["type"] = schema.get("type")
        checked_fields.append(checked)
        if not ok:
            differences.append(f"field mismatch: {field} expected={expected} actual={actual}")
    return {"differences": differences, "checked_fields": checked_fields}


def _verifiable_build_fields(build_request: dict[str, Any]) -> dict[str, Any]:
    skipped = {"proto", "protocol", "intent", "name", "port", "baudrate", "timeout", "has_address", "from_frame"}
    fields = {
        str(key): value for key, value in build_request.items()
        if key not in skipped and value not in ("", None)
    }
    datetime_parts = {
        key.rsplit(".", 1)[-1]: str(value).zfill(2)
        for key, value in fields.items()
        if key.startswith("datetime.")
    }
    if {"year", "month", "day", "hour", "minute", "second"}.issubset(datetime_parts):
        for key in list(fields):
            if key.startswith("datetime."):
                fields.pop(key)
        fields["datetime"] = (
            datetime_parts["year"] + datetime_parts["month"] + datetime_parts["day"] +
            datetime_parts["hour"] + datetime_parts["minute"] + datetime_parts["second"]
        )
    return fields


def _find_decoded_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            leaf = str(key).split(".")[-1]
            if leaf in (field, field.split(".")[-1]):
                return _compact_value(child)
            found = _find_decoded_field(child, field)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_decoded_field(child, field)
            if found is not None:
                return found
    return None


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict) and {"year", "month", "day", "hour", "minute", "second"}.issubset(value):
        return (
            str(value["year"]).zfill(2) + str(value["month"]).zfill(2) +
            str(value["day"]).zfill(2) + str(value["hour"]).zfill(2) +
            str(value["minute"]).zfill(2) + str(value["second"]).zfill(2)
        )
    return value


def _is_enum_decoded(value: Any) -> bool:
    return isinstance(value, dict) and "raw" in value


def _enum_raw(value: Any) -> Any:
    if _is_enum_decoded(value):
        return value["raw"]
    return value


def _schema_children(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    children = (schema or {}).get("children") or []
    return {
        str(item.get("name")): item
        for item in children
        if isinstance(item, dict) and item.get("name")
    }


def _values_match(expected: Any, actual: Any, schema: dict[str, Any] | None = None) -> bool:
    if actual is None:
        return False
    if str(expected).lower() == "uplink":
        return _normalize_compare_value(actual) in {"1", "uplink"}
    if str(expected).lower() == "downlink":
        return _normalize_compare_value(actual) in {"0", "downlink"}
    field_type = str((schema or {}).get("type") or "")

    if field_type == "array" or (isinstance(expected, list) and isinstance(actual, list)):
        if not isinstance(expected, list) or not isinstance(actual, list):
            return False
        if len(expected) != len(actual):
            return False
        child_schema = _schema_children(schema)
        scalar_child = next(iter(child_schema.values()), None) if len(child_schema) == 1 else None
        for exp_item, act_item in zip(expected, actual):
            if isinstance(exp_item, dict) and isinstance(act_item, dict):
                for key, exp_val in exp_item.items():
                    if not _values_match(exp_val, act_item.get(key), child_schema.get(key)):
                        return False
            elif not _values_match(exp_item, act_item, scalar_child):
                return False
        return True

    if field_type == "struct" or (
        isinstance(expected, dict)
        and isinstance(actual, dict)
        and not _is_enum_decoded(actual)
    ):
        child_schema = _schema_children(schema)
        for key, exp_val in expected.items():
            if not _values_match(exp_val, actual.get(key), child_schema.get(key)):
                return False
        return True

    if field_type == "enum" or _is_enum_decoded(actual):
        return _parse_decimal_or_prefixed_int(expected) == _parse_decimal_or_prefixed_int(_enum_raw(actual))

    if field_type.startswith("uint"):
        return _parse_decimal_or_prefixed_int(expected) == _parse_decimal_or_prefixed_int(actual)
    if field_type in {"bcd", "bcd_numeric"}:
        return _normalize_bcd_compare_value(expected) == _normalize_bcd_compare_value(actual)
    if field_type in {"hex", "bytes"}:
        return _normalize_hex_compare_value(expected) == _normalize_hex_compare_value(actual)
    expected_text = re.sub(r"\s+", "", str(expected).strip())
    actual_text = re.sub(r"\s+", "", str(_enum_raw(actual)).strip())
    if expected_text.isdigit() and actual_text.isdigit() and max(len(expected_text), len(actual_text)) > 2:
        return int(expected_text) == int(actual_text)
    return _normalize_compare_value(expected) == _normalize_compare_value(actual)


def _parse_decimal_or_prefixed_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = re.sub(r"\s+", "", str(value).strip())
    if re.fullmatch(r"0x[0-9a-fA-F]+", text):
        return int(text, 16)
    return int(text, 10)


def _normalize_hex_compare_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex().lower()
    if isinstance(value, dict) and "raw" in value:
        return _normalize_hex_compare_value(value["raw"])
    return re.sub(r"[^0-9A-Fa-f]", "", str(value)).lower()


def _normalize_bcd_compare_value(value: Any) -> str:
    normalized = _normalize_hex_compare_value(value)
    if len(normalized) <= 2:
        return normalized.zfill(2)[-2:]
    return normalized


def _normalize_compare_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        if _is_enum_decoded(value):
            return str(value["raw"])
        compacted = _compact_value(value)
        if compacted is not value:
            return _normalize_compare_value(compacted)
        return re.sub(r"\s+", "", str(value)).lower()
    text = str(value).strip()
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"0x[0-9a-fA-F]+", compact):
        return str(int(compact, 16))
    if re.fullmatch(r"[0-9A-Fa-f]{2}", compact):
        return str(int(compact, 16))
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}){2,}", compact):
        return compact.lower()
    return compact.lower()


def _detect_tasks(raw_input: str) -> list[TaskType]:
    text = raw_input.lower()
    has_hex = bool(_extract_hex(raw_input))
    frame_hex = _extract_hex(raw_input)
    frame_like = bool(frame_hex and _looks_like_protocol_frame(frame_hex))
    from_frame_intent = frame_like and any(
        word in raw_input for word in ["旧报文", "基于", "根据", "修改", "重建", "from_frame", "from-frame"]
    )
    wants_build = (
        any(word in raw_input for word in ["构造", "生成", "组帧", "回复", "响应", "添加", "设置", "查询", "读取", "重建"])
        or "build" in text
        or from_frame_intent
    )
    wants_decode = any(word in raw_input for word in ["解析", "解码"]) or "decode" in text
    wants_send = any(word in raw_input for word in ["发送", "下发", "写入", "执行"]) or "send" in text or bool(re.search(r"通过\s*COM\d+", raw_input, re.I))

    tasks: list[TaskType] = []
    if wants_build:
        tasks.append("BUILD")
    elif wants_decode or has_hex:
        tasks.append("DECODE")
    if wants_send:
        if not tasks and has_hex:
            tasks.append("SEND")
        elif "SEND" not in tasks:
            tasks.append("SEND")
    return tasks


def _extract_hex(raw_input: str) -> str:
    candidates = re.findall(r"(?:[0-9A-Fa-f]{2}[\s,;:-]*){4,}", raw_input)
    if not candidates:
        return ""
    clean = re.sub(r"[^0-9A-Fa-f]", "", max(candidates, key=len))
    return " ".join(clean[index:index + 2].upper() for index in range(0, len(clean), 2))


def _is_from_frame_build(
    raw_input: str,
    tasks: list[TaskType],
    facts: dict[str, Any] | None = None,
) -> bool:
    if "BUILD" not in tasks:
        return False
    if facts and facts.get("from_frame_hex"):
        return True
    hex_text = _extract_hex(raw_input)
    if not hex_text or not _looks_like_protocol_frame(hex_text):
        return False
    if any(word in raw_input for word in ["旧报文", "基于", "根据", "修改", "重建", "from_frame", "from-frame"]):
        return True
    return any(word in raw_input for word in ["构造", "生成", "组帧", "回复", "响应", "添加", "设置", "查询", "读取"]) or "build" in raw_input.lower()


def _looks_like_protocol_frame(hex_text: str) -> bool:
    clean = re.sub(r"\s+", "", hex_text).upper()
    if len(clean) < 16:
        return False
    no_fe = clean
    while no_fe.startswith("FE"):
        no_fe = no_fe[2:]
    if no_fe.startswith("68") and len(no_fe) >= 24 and no_fe[14:16] == "68":
        return True
    if no_fe.startswith("68") and len(no_fe) >= 12:
        return True
    return False


def _source_frame_hex(record: RunRecord) -> str:
    if record.facts.get("from_frame_hex"):
        return str(record.facts["from_frame_hex"]).strip()
    return _extract_hex(record.raw_input)


def _detect_protocol(frame_hex: str) -> str:
    clean = re.sub(r"\s+", "", frame_hex).upper()
    no_fe = clean
    while no_fe.startswith("FE"):
        no_fe = no_fe[2:]
    if no_fe.startswith("68") and len(no_fe) >= 24 and no_fe[14:16] == "68":
        return "dlt645"
    if no_fe.startswith("68") and len(no_fe) >= 12:
        return "csg"
    return ""


def _normalize_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(user_input)
    if "protocol" in normalized and "proto" not in normalized:
        normalized["proto"] = normalized.pop("protocol")
    if "hex" in normalized and "frame_hex" not in normalized:
        normalized["frame_hex"] = normalized.pop("hex")
    if "from_frame" in normalized and "from_frame_hex" not in normalized:
        normalized["from_frame_hex"] = normalized.pop("from_frame")
    if "add" in normalized and "has_address" not in normalized:
        normalized["has_address"] = _coerce_bool(normalized.pop("add"))
    if isinstance(normalized.get("route_params"), dict):
        route_params = dict(normalized["route_params"])
        if "add" in route_params and "has_address" not in route_params:
            route_params["has_address"] = _coerce_bool(route_params.pop("add"))
        normalized["route_params"] = route_params
    return normalized


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _is_waiting_for_protocol_match(record: RunRecord) -> bool:
    return (
        record.state == "WAITING_INPUT"
        and record.waiting_input.get("field") == "protocol_match"
        and not record.route_result
        and not _route_args(record.facts)
    )


def _has_route_input(user_input: dict[str, Any]) -> bool:
    if user_input.get("entry_id") or user_input.get("route_params"):
        return True
    return any(key in user_input for key in ("proto", "protocol", "func", "afn", "di", "dir", "has_address", "add"))


def _complete_task(record: RunRecord, task: TaskType) -> None:
    label = _task_label(task)
    record.task_plan.completed.append(label)
    record.task_plan.current_index += 1
    record.task_plan.pending = [_task_label(t) for t in record.task_plan.tasks[record.task_plan.current_index:]]
    _append_event(record, "task_completed", {"task": label})


def _dependencies(tasks: list[TaskType]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {}
    if "SEND" in tasks and "BUILD" in tasks:
        deps["SEND"] = ["BUILD", "DECODE_VERIFY"]
    if "SEND" in tasks and "DECODE" in tasks:
        deps["SEND"] = ["DECODE"]
    return deps


def _task_label(task: TaskType) -> str:
    return "BUILD+DECODE_VERIFY" if task == "BUILD" else task


def _wait(
    record: RunRecord,
    field: str,
    message: str,
    *,
    examples: list[Any] | None = None,
    protocol_map_ref: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> None:
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": field,
        "message": message,
        "examples": examples or [],
    }
    if protocol_map_ref is not None:
        record.waiting_input["protocol_map_ref"] = protocol_map_ref
    if candidates is not None:
        record.waiting_input["candidates"] = candidates
    _append_event(record, "mcp_exit_waiting_input", record.waiting_input)


def _debug_enabled(debug: bool | None) -> bool:
    if debug is not None:
        return bool(debug)
    return os.getenv("WIREFORGE_MCP_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def _public_result(record: RunRecord, *, debug: bool = False) -> dict[str, Any]:
    if debug:
        return _debug_public_result(record)
    return _fit_response_budget(_compact_public_result(record), record.raw_input)


def _compact_public_result(record: RunRecord) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": record.run_id,
        "state": record.state,
    }
    if record.error:
        result["error"] = record.error

    if record.state == "WAITING_INPUT":
        result.update(_compact_waiting_input(record.waiting_input))
    elif record.state == "SUCCEEDED":
        result.update(_compact_success(record))
    elif isinstance(record.results, dict):
        for key in ("bootstrap", "reason"):
            if key in record.results:
                result[key] = record.results[key]
        if isinstance(record.results.get("build"), dict) and record.results["build"].get("frame"):
            result["final_frame"] = record.results["build"]["frame"]
    return result


def _compact_waiting_input(waiting_input: dict[str, Any]) -> dict[str, Any]:
    field = str(waiting_input.get("field") or "")
    public: dict[str, Any] = {"need": field}
    if field == "protocol_match":
        protocol_map_ref = waiting_input.get("protocol_map_ref") if isinstance(waiting_input.get("protocol_map_ref"), dict) else {}
        if protocol_map_ref.get("entry_count") is not None:
            public["map_entries"] = protocol_map_ref["entry_count"]
        candidates = waiting_input.get("candidates") if isinstance(waiting_input.get("candidates"), list) else []
        public["candidates"] = [_compact_candidate(candidate) for candidate in candidates[:3]]
        return public
    if field == "values":
        route = waiting_input.get("route") if isinstance(waiting_input.get("route"), dict) else {}
        if waiting_input.get("source_mode") == "from_frame":
            public["source_mode"] = "from_frame"
            decoded = _compact_decode_values(waiting_input.get("decoded_values"))
            if decoded:
                public["decoded_values"] = decoded
        public["variant_id"] = route.get("variant_id")
        public["route"] = waiting_input.get("route_params") or route.get("locator") or {}
        public["route_detail"] = _public_route(route)
        fields = waiting_input.get("required_fields") or waiting_input.get("missing_fields")
        if not fields and isinstance(waiting_input.get("input_schema"), list):
            fields = [item.get("name") for item in waiting_input["input_schema"] if isinstance(item, dict) and item.get("name")]
        public["fields"] = fields or []
        schema = waiting_input.get("input_schema") if isinstance(waiting_input.get("input_schema"), list) else []
        public["input_schema"] = schema
        if waiting_input.get("source_mode") == "from_frame":
            public["required_fields"] = []
            public["fields"] = []
        else:
            public["required_fields"] = [
                item.get("name")
                for item in schema
                if isinstance(item, dict) and item.get("required") and item.get("name")
            ]
        defaulted = {
            item.get("name"): item.get("default")
            for item in schema
            if isinstance(item, dict) and item.get("name") and "default" in item
        }
        if defaulted:
            public["defaulted_fields"] = defaulted
        derived = route.get("derived_fields") if isinstance(route.get("derived_fields"), dict) else {}
        if derived:
            public["derived_fields"] = {
                key: value
                for key, value in derived.items()
                if isinstance(value, dict) and value.get("method")
            }
        elif isinstance(route.get("derived_fields"), dict):
            public["derived_fields"] = route.get("derived_fields") or {}
        if waiting_input.get("missing_fields"):
            public["missing_fields"] = waiting_input["missing_fields"]
        for key in ("attempt", "max_attempts", "error"):
            if waiting_input.get(key) not in (None, ""):
                public[key] = waiting_input[key]
        return public
    if waiting_input.get("examples"):
        public["examples"] = waiting_input["examples"]
    if waiting_input.get("message"):
        public["message"] = waiting_input["message"]
    return public


def _compact_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    public = {
        "id": entry.get("entry_id") or entry.get("id"),
        "desc": entry.get("description") or entry.get("name"),
        "route": entry.get("route_params") or {},
    }
    return {key: value for key, value in public.items() if value not in (None, "", [], {})}


def _compact_decode_values(values: dict[str, Any] | None, depth: int = 0) -> dict[str, Any] | None:
    """Compact decoded values for agent consumption without truncating lists.

    Depth 0: keep all top-level keys, recurse into dicts.
    Depth >= 2: replace dicts with their key count summary.
    Lists are never abbreviated — callers rely on full array values (e.g. nodes[]).
    """
    if not isinstance(values, dict):
        return values
    if depth >= 2:
        return {"_keys": sorted(values.keys()), "_count": len(values)}
    result: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(val, dict):
            result[key] = _compact_decode_values(val, depth + 1)
        else:
            result[key] = val
    return result


def _compact_success(record: RunRecord) -> dict[str, Any]:
    public: dict[str, Any] = {}
    build = record.results.get("build") if isinstance(record.results, dict) else None
    route = record.results.get("route") if isinstance(record.results, dict) else None
    decode_verify = record.results.get("decode_verify") if isinstance(record.results, dict) else None
    decode = record.results.get("decode") if isinstance(record.results, dict) else None
    send = record.results.get("send") if isinstance(record.results, dict) else None

    if isinstance(build, dict):
        if build.get("frame"):
            public["final_frame"] = build["frame"]
        if build.get("protocol"):
            public["protocol"] = build["protocol"]
    if isinstance(route, dict) and route.get("variant_id"):
        public["variant_id"] = route["variant_id"]
    if isinstance(decode_verify, dict):
        public["decode_verified"] = not bool(decode_verify.get("differences"))
        checked_fields = decode_verify.get("checked_fields") if isinstance(decode_verify.get("checked_fields"), list) else []
        if checked_fields:
            public["checks"] = [
                [item.get("field"), bool(item.get("ok"))]
                for item in checked_fields
                if isinstance(item, dict)
            ]
    if isinstance(decode, dict):
        public["decode"] = {
            key: value
            for key, value in {
                "protocol": decode.get("protocol"),
                "path": decode.get("path"),
                "frame": decode.get("frame"),
                "values": _compact_decode_values(decode.get("values")),
            }.items()
            if value not in (None, "", [], {})
        }
    if isinstance(send, dict):
        public["send"] = send
    return public


def _fit_response_budget(result: dict[str, Any], raw_input: str) -> dict[str, Any]:
    # Hex payloads must never be shortened to fit the budget.
    if _has_complete_hex_payload(result):
        return result

    budget = _response_budget(raw_input)
    if _json_size(result) <= budget:
        return result

    compact = json.loads(json.dumps(result, ensure_ascii=False))
    if _has_complete_hex_payload(compact):
        return compact
    candidates = compact.get("candidates")
    if isinstance(candidates, list):
        while len(candidates) > 1 and _json_size(compact) > budget:
            candidates.pop()
        if _json_size(compact) > budget:
            for candidate in candidates:
                if isinstance(candidate, dict):
                    candidate.pop("desc", None)
        if _json_size(compact) > budget and candidates:
            compact["candidates"] = candidates[:1]
    return compact


def _has_complete_hex_payload(result: dict[str, Any]) -> bool:
    """True when the response carries a full frame hex that must not be budget-trimmed."""
    if result.get("final_frame"):
        return True
    decode = result.get("decode")
    if isinstance(decode, dict) and decode.get("frame"):
        return True
    return False


def _response_budget(raw_input: str) -> int:
    ratio = _env_int("WIREFORGE_MCP_MAX_RATIO", DEFAULT_RESPONSE_MAX_RATIO)
    minimum = _env_int("WIREFORGE_MCP_MIN_BYTES", DEFAULT_RESPONSE_MIN_BYTES)
    return max(minimum, len(raw_input.encode("utf-8")) * max(1, ratio))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _debug_public_result(record: RunRecord) -> dict[str, Any]:
    result = {
        "run_id": record.run_id,
        "state": record.state,
        "raw_input": record.raw_input,
        "error": record.error,
        "log_dir": str(_run_dir(record.run_id)),
        "workflow_log": str(WORKFLOW_LOG),
    }
    if record.state == "WAITING_INPUT":
        result["waiting_input"] = _public_waiting_input(record.waiting_input)
    else:
        result["waiting_input"] = {}
    build = record.results.get("build") if isinstance(record.results, dict) else None
    route = record.results.get("route") if isinstance(record.results, dict) else None
    decode_verify = record.results.get("decode_verify") if isinstance(record.results, dict) else None
    result["results"] = _public_results(record.results, state=record.state)
    if isinstance(build, dict) and build.get("frame"):
        result["final_frame"] = build["frame"]
    if isinstance(build, dict) and build.get("protocol"):
        result["protocol"] = build["protocol"]
    if isinstance(route, dict) and route.get("variant_id"):
        result["variant_id"] = route["variant_id"]
    if isinstance(decode_verify, dict):
        result["decode_verified"] = not bool(decode_verify.get("differences"))
    return result


def _full_protocol_map() -> dict[str, Any]:
    return load_protocol_map()


def _protocol_map_ref(protocol_map: dict[str, Any]) -> dict[str, Any]:
    protocols = {
        proto: {
            "name": info.get("name") or proto,
            "entries": len(info.get("entries") or []),
        }
        for proto, info in (protocol_map.get("protocols") or {}).items()
    }
    return {
        "path": str(ROOT / "compiled" / "protocol_map.json"),
        "version": protocol_map.get("version", 1),
        "entry_count": _map_entry_count(protocol_map),
        "protocols": protocols,
    }


def _candidate_entries(protocol_map: dict[str, Any], raw_input: str, *, limit: int = 3) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    query = raw_input.lower()
    query_chars = {ch for ch in query if not ch.isspace()}
    for info in (protocol_map.get("protocols") or {}).values():
        for entry in info.get("entries") or []:
            description = str(entry.get("description") or "")
            text = " ".join([
                str(entry.get("name") or ""),
                description,
                " ".join(str(part) for part in (entry.get("path") or [])),
                " ".join(str(field) for field in (entry.get("fields") or [])),
                json.dumps(entry.get("route_params") or {}, ensure_ascii=False),
            ]).lower()
            score = 0
            if text and query:
                if description and description in raw_input:
                    score += len(description) * 20
                for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", query):
                    if token and token in text:
                        score += len(token) * 8
                score += sum(1 for ch in query_chars if ch in text)
            if entry.get("fields"):
                score += 1
            if score > 0:
                scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    entries: list[dict[str, Any]] = []
    seen_leaf_ids: set[str] = set()
    for _, entry in scored:
        leaf_id = str(entry.get("leaf_id") or entry.get("id") or "")
        if leaf_id in seen_leaf_ids:
            continue
        seen_leaf_ids.add(leaf_id)
        entries.append(_public_entry(entry, compact=True))
        if len(entries) >= limit:
            break
    return entries


def _map_entry_count(protocol_map: dict[str, Any]) -> int:
    return sum(len(proto.get("entries") or []) for proto in (protocol_map.get("protocols") or {}).values())


def _public_waiting_input(waiting_input: dict[str, Any]) -> dict[str, Any]:
    public = dict(waiting_input)
    public.pop("protocol_map", None)
    if isinstance(public.get("route"), dict):
        public["route"] = _public_route(public["route"], compact=True)
    if isinstance(public.get("result"), dict):
        public["result"] = _handler_summary(public["result"])
    return public


def _public_results(results: dict[str, Any], *, state: str = "") -> dict[str, Any]:
    if state == "SUCCEEDED":
        public: dict[str, Any] = {}
        if isinstance(results.get("build"), dict):
            public["build"] = _public_build(results["build"], compact=True)
        if isinstance(results.get("decode_verify"), dict):
            public["decode_verify"] = _public_decode_verify(results["decode_verify"], compact=True)
        if isinstance(results.get("decode"), dict):
            public["decode"] = _public_decode(results["decode"], compact=True)
        if isinstance(results.get("send"), dict):
            public["send"] = results["send"]
        return public

    public: dict[str, Any] = {}
    if isinstance(results.get("protocol_match"), dict):
        public["protocol_match"] = _public_entry(results["protocol_match"], compact=True)
    if isinstance(results.get("route_request"), dict):
        public["route_request"] = dict(results["route_request"])
    if state != "WAITING_INPUT" and isinstance(results.get("route"), dict):
        public["route"] = _public_route(results["route"], compact=True)
    if isinstance(results.get("build_request"), dict):
        public["build_request"] = dict(results["build_request"])
    if isinstance(results.get("build"), dict):
        public["build"] = _public_build(results["build"])
    if isinstance(results.get("decode_verify"), dict):
        public["decode_verify"] = _public_decode_verify(results["decode_verify"])
    if isinstance(results.get("decode"), dict):
        public["decode"] = _public_decode(results["decode"])
    if isinstance(results.get("send"), dict):
        public["send"] = results["send"]
    for key in ("bootstrap", "reason", "build_error"):
        if key in results:
            public[key] = results[key]
    return public


def _public_entry(entry: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    public = {
        "entry_id": entry.get("entry_id") or entry.get("id"),
        "name": entry.get("name"),
        "description": entry.get("description"),
        "route_params": entry.get("route_params") or {},
        "fields": entry.get("fields") or [],
    }
    if not compact:
        public["id"] = entry.get("id")
        public["leaf_id"] = entry.get("leaf_id")
        public["path"] = entry.get("path") or []
    return public


def _public_route(route: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    public = {
        "protocol": route.get("protocol"),
        "variant_id": route.get("variant_id"),
        "locator": route.get("locator") or {},
    }
    if not compact:
        public["input_schema"] = route.get("input_schema") or []
        public["path"] = route.get("path")
        public["message_id"] = route.get("message_id")
        public["derived_fields"] = route.get("derived_fields") or {}
        public["frame_defaults"] = route.get("frame_defaults") or {}
    return public


def _public_build(build: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    public = {
        "protocol": build.get("protocol"),
        "frame": build.get("frame"),
    }
    if not compact:
        public["path"] = build.get("path")
        public["resolved"] = build.get("resolved") or {}
    return public


def _public_decode_verify(decode_verify: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    decode = decode_verify.get("decode") if isinstance(decode_verify.get("decode"), dict) else {}
    public = {
        "frame": decode.get("frame"),
        "differences": decode_verify.get("differences") or [],
        "checked_fields": decode_verify.get("checked_fields") or [],
    }
    if not compact:
        public["path"] = decode.get("path")
    return public


def _public_decode(decode: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    public = {
        "protocol": decode.get("protocol"),
        "path": decode.get("path"),
        "frame": decode.get("frame"),
    }
    if not compact:
        public["values"] = decode.get("values") or {}
    return public


def _load_or_create(run_id: str | None, raw_input: str | None) -> RunRecord:
    rid = run_id or uuid.uuid4().hex
    path = _run_dir(rid) / "state.json"
    if path.exists():
        record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if raw_input and raw_input != record.raw_input:
            raise ValueError(
                "run_id belongs to an existing task with different raw_input. "
                "Use user_input to continue this run, or omit run_id to start a new task."
            )
        return record
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
    (_run_dir(record.run_id) / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(record: RunRecord, name: str, text: str) -> None:
    (_run_dir(record.run_id) / name).write_text(text, encoding="utf-8")


def _append_event(record: RunRecord, event: str, data: dict[str, Any]) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "timestamp": timestamp,
        "run_id": record.run_id,
        "state": record.state,
        "event": event,
        "data": data,
    }
    _run_dir(record.run_id).mkdir(parents=True, exist_ok=True)
    with (_run_dir(record.run_id) / "events").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    _append_workflow_log(record, event, data, timestamp)


def _append_workflow_log(record: RunRecord, event: str, data: dict[str, Any], timestamp: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WORKFLOW_LOG.open("a", encoding="utf-8") as handle:
        handle.write(_format_workflow_log(record, event, data, timestamp))


def _format_workflow_log(record: RunRecord, event: str, data: dict[str, Any], timestamp: str) -> str:
    lines = [f"[{timestamp}] run={record.run_id} state={record.state} step={event}"]
    if event == "enter":
        lines.append(f"raw_input: {record.raw_input}")
        lines.append(f"user_input: {_inline(data.get('user_input') or {})}")
    elif event == "map_ready":
        lines.append(f"protocol_map.entries: {data.get('entries')}")
        lines.append(f"protocol_map.protocols: {_inline(data.get('protocols') or [])}")
    elif event in {"route_request", "build_request", "decode_request", "send_request"}:
        lines.extend(["request:", *_mapping_lines(data)])
    elif event.endswith("_result") or event == "send_open_result":
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else _handler_summary(data)
        lines.append(f"success: {summary.get('success')}")
        lines.append(f"error: {summary.get('error') or ''}")
        if summary.get("frame"):
            lines.append(f"frame: {summary['frame']}")
    elif event == "decode_verify_checked":
        lines.append("checked_fields:")
        for item in data.get("checked_fields") or []:
            lines.append(f"  - {item['field']}: expected={item['expected']} actual={item['actual']} ok={item['ok']}")
    elif event.startswith("mcp_exit"):
        lines.append(f"mcp_exit_state: {record.state}")
        lines.append(f"waiting_input: {_inline(data)}")
    elif event == "failed":
        lines.append(f"error: {data.get('error') or record.error}")
    elif event == "round_exit":
        lines.append(f"mcp_exit_state: {data.get('mcp_exit_state') or record.state}")
        if data.get("error"):
            lines.append(f"error: {data['error']}")
        build = record.results.get("build") if isinstance(record.results, dict) else None
        if isinstance(build, dict) and build.get("frame"):
            lines.append(f"final_frame: {build['frame']}")
    elif event == "succeeded":
        lines.append(f"completed: {_inline(data.get('completed') or [])}")
    return "\n".join(lines) + "\n\n"


def _handler_summary(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else {}
    return {
        "success": result.get("success") if isinstance(result, dict) else None,
        "status": result.get("status") if isinstance(result, dict) else None,
        "error": result.get("error") if isinstance(result, dict) else None,
        "frame": data.get("frame") if isinstance(data, dict) else None,
    }


def _result_summary(results: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("route", "build", "decode", "decode_verify", "send"):
        if key in results:
            value = results[key]
            if isinstance(value, dict):
                summary[key] = sorted(value.keys())
            else:
                summary[key] = str(type(value).__name__)
    return summary


def _mapping_lines(data: dict[str, Any]) -> list[str]:
    return [f"  {key}: {_inline(value)}" for key, value in data.items()]


def _inline(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text[:700] + "..." if len(text) > 700 else text
