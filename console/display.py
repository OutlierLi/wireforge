"""CLI 终端紧凑显示 — 与 protocol-tui.v1 响应分离。

成功时部分命令只输出关键信息；失败或非白名单命令仍走全量渲染。
"""

from __future__ import annotations

import json
from typing import Any, TextIO

_CONTAINER_FIELDS = frozenset({
    "data", "user_data", "di_data", "data_content", "freeze_payload",
})


def wire_fields_from_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 decode trace 提取带字节偏移的扁平字段列表。"""
    fields: list[dict[str, Any]] = []
    payload_base: int | None = None
    seen_paths: set[str] = set()

    for ev in trace:
        field = str(ev.get("field") or "")
        ftype = str(ev.get("type") or "")
        raw = ev.get("raw")
        if not raw:
            continue

        pos = int(ev.get("position", 0))

        if ftype == "routed_payload":
            if field in _CONTAINER_FIELDS:
                payload_base = pos
                continue
            payload_base = pos

        abs_pos = pos
        if payload_base is not None and ftype != "routed_payload" and pos < payload_base:
            abs_pos = payload_base + pos

        if ftype == "bitset":
            val = ev.get("value")
            if isinstance(val, dict):
                for sub, sub_val in val.items():
                    if sub == "raw":
                        continue
                    path = f"{field}.{sub}"
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    fields.append({
                        "offset": abs_pos,
                        "path": path,
                        "wire_hex": raw,
                        "value": sub_val,
                    })
            continue

        if field in _CONTAINER_FIELDS and ftype == "routed_payload":
            continue

        if field in seen_paths:
            continue
        seen_paths.add(field)

        fields.append({
            "offset": abs_pos,
            "path": field,
            "wire_hex": raw,
            "value": ev.get("value"),
        })

    fields.sort(key=lambda item: (item["offset"], item["path"]))
    return fields


def _format_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex(" ").upper()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def format_decode_fields(data: dict[str, Any]) -> list[str]:
    """decode 成功：扁平字段 + 字节对照。"""
    lines: list[str] = []
    frame = data.get("frame")
    if frame:
        lines.append(str(frame))

    wire_fields = data.get("fields")
    if not wire_fields and data.get("trace"):
        wire_fields = wire_fields_from_trace(data["trace"])

    for item in wire_fields or []:
        offset = item.get("offset", 0)
        path = item.get("path", "")
        wire_hex = item.get("wire_hex", "")
        value = _format_value(item.get("value"))
        lines.append(f"@{offset:02d}  {path:<24} [{wire_hex}]  {value}")
    return lines


def _command_sub(args: dict[str, Any]) -> str:
    sub = str(args.get("sub") or "")
    if sub:
        return sub
    pos = args.get("_") or []
    return str(pos[0]) if pos else ""


def _parse_command_line(command_line: str) -> tuple[str, dict[str, Any]]:
    from console.runtime import parse_command_text

    text = command_line.strip()
    if not text:
        return "", {}
    if not text.startswith("/"):
        text = f"/{text}"
    return parse_command_text(text)


def try_compact_display(command_line: str, response: dict[str, Any]) -> list[str] | None:
    """若命中紧凑显示规则则返回输出行，否则 None（走全量渲染）。"""
    if response.get("status") != "success":
        return None

    command, args = _parse_command_line(command_line)
    if not command:
        return None

    data = response.get("data") or {}

    if command == "build":
        frame = data.get("frame")
        if frame and not data.get("input_schema"):
            return [f"[build]: {frame}"]

    if command == "serial" and _command_sub(args) == "send":
        sent = data.get("sent")
        if sent:
            target = data.get("to") or data.get("id") or "default"
            return [f"[{target}] TX: {sent}"]

    if command == "decode":
        lines = format_decode_fields(data)
        if lines:
            return lines

    if command == "upg":
        sent = data.get("sent_segments")
        total = data.get("total_segments")
        duration = data.get("duration_seconds")
        if sent is not None and total is not None:
            return [f"[upg]: success {sent}/{total} segments, {duration}s"]

    return None


def _render_build_response(response: dict[str, Any], stdout: TextIO) -> None:
    """build 命令专用渲染：成功/失败均带 [build]: 标识。"""
    tag = "build"
    if response.get("status") == "success":
        data = response.get("data") or {}
        frame = data.get("frame")
        if frame and not data.get("input_schema"):
            stdout.write(f"[{tag}]: {frame}\n")
            return

    status = response.get("status", "error")
    if status == "success":
        stdout.write(f"[{tag}]: success\n")
        _render_value(response.get("data") or {}, stdout, 1)
        return

    if status == "need_input":
        stdout.write(f"[{tag}]: need input\n")
        for item in response.get("input_schema", []):
            key = item.get("key") or item.get("name") or ""
            type_name = item.get("type", "str")
            examples = item.get("examples") or []
            suffix = f"  e.g. {', '.join(str(x) for x in examples[:3])}" if examples else ""
            stdout.write(f"  --{key}: {type_name}{suffix}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    if status == "need_disambiguation":
        stdout.write(f"[{tag}]: need disambiguation {response.get('key', '')}\n")
        for item in response.get("candidates", []):
            stdout.write(f"  {item.get('label') or item.get('value')}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    error = response.get("error") or status
    stdout.write(f"[{tag}]: {status}: {error}\n")
    detail = response.get("detail")
    if detail:
        _render_value(detail, stdout, 1)
    path = response.get("path")
    if path and not detail:
        stdout.write(f"  path: {path}\n")


def _render_upg_response(response: dict[str, Any], stdout: TextIO) -> None:
    tag = "upg"
    if response.get("status") == "success":
        compact = try_compact_display("/upg", response)
        if compact:
            for line in compact:
                stdout.write(f"{line}\n")
            return
        stdout.write(f"[{tag}]: success\n")
        _render_value(response.get("data") or {}, stdout, 1)
        return

    status = response.get("status", "error")
    error = response.get("error") or status
    stdout.write(f"[{tag}]: {error}\n")
    detail = response.get("detail") or {}
    reason = detail.get("failure_reason") or error
    if reason:
        stdout.write(f"  reason: {reason}\n")
    label = detail.get("last_label")
    if label:
        stdout.write(f"  step: {label}\n")
    if detail.get("last_tx_hex"):
        stdout.write(f"  last_tx: {detail['last_tx_hex']}\n")
    if detail.get("last_rx_hex"):
        stdout.write(f"  last_rx: {detail['last_rx_hex']}\n")
    if detail.get("last_rx_di"):
        stdout.write(f"  last_rx_di: {detail['last_rx_di']}\n")


def render_response(command_line: str, response: dict[str, Any], stdout: TextIO) -> None:
    """渲染命令响应到终端。"""
    command, _args = _parse_command_line(command_line)
    if command == "build":
        _render_build_response(response, stdout)
        return
    if command == "upg":
        _render_upg_response(response, stdout)
        return

    compact = try_compact_display(command_line, response)
    if compact is not None:
        for line in compact:
            stdout.write(f"{line}\n")
        return

    status = response.get("status", "error")
    if status == "success":
        data = response.get("data") or {}
        stdout.write("success\n")
        _render_value(data, stdout, 1)
        return

    if status == "need_input":
        stdout.write("need input\n")
        for item in response.get("input_schema", []):
            key = item.get("key") or item.get("name") or ""
            type_name = item.get("type", "str")
            examples = item.get("examples") or []
            suffix = f"  e.g. {', '.join(str(x) for x in examples[:3])}" if examples else ""
            stdout.write(f"  --{key}: {type_name}{suffix}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    if status == "need_disambiguation":
        stdout.write(f"need disambiguation {response.get('key', '')}\n")
        for item in response.get("candidates", []):
            stdout.write(f"  {item.get('label') or item.get('value')}\n")
        hint = response.get("hint")
        if hint:
            stdout.write(f"  {hint}\n")
        return

    error = response.get("error") or status
    stdout.write(f"{status}: {error}\n")
    detail = response.get("detail")
    if detail:
        _render_value(detail, stdout, 1)


def _render_value(value: Any, stdout: TextIO, depth: int = 0, key: str = "") -> None:
    indent = "  " * depth
    prefix = f"{indent}{key}: " if key else indent
    if isinstance(value, dict):
        if key:
            stdout.write(f"{indent}{key}:\n")
        for child_key, child_value in value.items():
            _render_value(child_value, stdout, depth + (1 if key else 0), str(child_key))
        return
    if isinstance(value, list):
        if key:
            stdout.write(f"{indent}{key}:\n")
        for item in value:
            if isinstance(item, (dict, list)):
                stdout.write(f"{indent}  -\n")
                _render_value(item, stdout, depth + 2)
            else:
                stdout.write(f"{indent}  - {item}\n")
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        stdout.write(f"{prefix}{value}\n")
        return
    stdout.write(f"{prefix}{json.dumps(value, ensure_ascii=False)}\n")
