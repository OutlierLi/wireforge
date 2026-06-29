"""Execution test report — structured template for real serial runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from test_runner.context import RunContext, StepRecord
from test_runner.error_codes import (
    AUTO_RULE_FAILED,
    BUILD_FAILED,
    MATCH_FAILED,
    PLAN_BUILD_SCHEMA_MISMATCH,
    PLAN_VAR_UNRESOLVED,
    RUN_TIMEOUT,
    SERIAL_NOT_CONNECTED,
    WAIT_FRAME_TIMEOUT,
    RunError,
    extract_diagnostics,
)

EXECUTION_REPORT_VERSION = 1

_ERROR_HINTS: dict[str, list[str]] = {
    WAIT_FRAME_TIMEOUT: [
        "确认串口已连接且 port/baudrate 正确",
        "增大 wait-frame 的 timeout_ms 或检查对端是否在线",
        "send 后接 wait-frame 时 send 的 timeout 应为 0",
    ],
    MATCH_FAILED: [
        "对照 frames.log 中 last_decoded 与 expect 条件",
        "确认 AFN/DI/dir 与协议文档一致",
    ],
    SERIAL_NOT_CONNECTED: [
        "检查 serial.connect 是否在 setup 中成功执行",
        "确认 options.vars.port 覆盖为真实设备路径",
    ],
    BUILD_FAILED: [
        "先用 test MCP validate/dry_run 校验 build 字段",
        "对照 protocol MCP 的 input_schema 补全参数",
    ],
    PLAN_BUILD_SCHEMA_MISMATCH: [
        "build 字段名与 route input_schema 不一致",
        "运行 test.dry_run 查看 unknown_fields / missing_required",
    ],
    PLAN_VAR_UNRESOLVED: [
        "检查 vars 或 exec_test.run options.vars 是否传入所需变量",
        "确认 ${...} 引用路径与 plan 中 save_as / loop 变量一致",
    ],
    RUN_TIMEOUT: [
        "增大 plan timeout_ms 或 exec_test.run options.timeout_ms",
        "检查是否有步骤阻塞未返回",
    ],
    AUTO_RULE_FAILED: [
        "mock://auto 场景检查 auto_rule.match 是否为 build 下行 DI 片段",
        "then 使用 dict 格式: command + args.hex，或 command: build + $request",
        "mock://auto 无规则命中时不回复，setup 须显式 auto_rule.add",
    ],
}


def extract_test_metadata(plan: dict[str, Any]) -> dict[str, Any]:
    """Optional plan-level fields for execution report header."""
    meta: dict[str, Any] = {}
    if plan.get("purpose"):
        meta["purpose"] = str(plan["purpose"])
    if plan.get("description"):
        meta["description"] = str(plan["description"])
    expected = plan.get("expected_results")
    if expected is not None:
        meta["expected_results"] = expected
    flow = plan.get("test_flow")
    if flow is not None:
        meta["test_flow"] = flow
    if plan.get("report_interactions"):
        meta["report_interactions"] = plan["report_interactions"]
    if plan.get("doc"):
        meta["doc"] = str(plan["doc"])
    return meta


def extract_serial_trace(records: list[StepRecord]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for record in records:
        entry = _serial_entry(record)
        if entry:
            trace.append(entry)
    return trace


def build_error_analysis(
    *,
    status: str,
    primary_error: RunError | None,
    records: list[StepRecord],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if status == "success":
        return {"status": "pass", "summary": "all steps passed"}

    if primary_error is None:
        failed = [r for r in records if r.status != "ok"]
        if not failed:
            return {"status": "fail", "summary": "run failed without step error detail"}
        last = failed[-1]
        return {
            "status": "fail",
            "summary": last.error or "step failed",
            "failed_step": last.id,
            "failed_action": last.action,
        }

    code = primary_error.code
    analysis: dict[str, Any] = {
        "status": "fail",
        "code": code,
        "summary": primary_error.message,
        "failed_step": primary_error.step_id,
        "diagnostics": extract_diagnostics(primary_error),
        "hints": list(_ERROR_HINTS.get(code, [])),
    }
    details = primary_error.details or {}
    if details.get("mismatch_summary"):
        analysis["mismatch_summary"] = details["mismatch_summary"]
    if details.get("received_frames") is not None:
        analysis["received_frames"] = details["received_frames"]
    if details.get("last_decoded"):
        analysis["last_decoded"] = details["last_decoded"]

    expected = metadata.get("expected_results")
    if expected and primary_error.step_id:
        analysis["expected_at_failure"] = _match_expected(expected, primary_error.step_id)

    analysis["recommendations"] = _recommendations(code, primary_error, records)
    return analysis


def build_execution_report(
    *,
    ctx: RunContext,
    plan: dict[str, Any],
    status: str,
    error_text: str = "",
    primary_error: RunError | None = None,
    total_ms: int = 0,
) -> dict[str, Any]:
    metadata = extract_test_metadata(plan)
    passed = sum(1 for r in ctx.records if r.status == "ok")
    failed = sum(1 for r in ctx.records if r.status != "ok")
    return {
        "version": EXECUTION_REPORT_VERSION,
        "run_id": ctx.run_id,
        "name": ctx.plan_name,
        "status": status,
        "started_at": ctx.start_time.isoformat(timespec="seconds"),
        "elapsed_ms": total_ms,
        "report_dir": str(ctx.report_dir),
        "test_metadata": metadata,
        "environment": {
            "vars": dict(ctx.vars),
            "dry_run": ctx.dry_run,
            "plan_file": str(ctx.plan_path) if ctx.plan_path else None,
        },
        "execution_summary": {
            "total_steps": len(ctx.records),
            "passed": passed,
            "failed": failed,
            "failed_step": ctx.failed_step or None,
            "teardown_errors": ctx.teardown_errors or None,
        },
        "steps": [
            {
                "id": r.id,
                "action": r.action,
                "status": r.status,
                "elapsed_ms": r.elapsed_ms,
                "error": r.error or None,
            }
            for r in ctx.records
        ],
        "serial_trace": extract_serial_trace(ctx.records),
        "comm_interactions": group_comm_interactions(
            ctx.records,
            metadata,
            started_at=ctx.start_time.isoformat(timespec="seconds"),
        ),
        "error_analysis": build_error_analysis(
            status=status,
            primary_error=primary_error,
            records=ctx.records,
            metadata=metadata,
        ),
        "error": error_text or None,
        "structured_error": primary_error.to_dict() if primary_error else None,
    }


def render_execution_report_md(report: dict[str, Any]) -> str:
    meta = report.get("test_metadata") or {}
    passed = report.get("status") == "success"
    analysis = report.get("error_analysis") or {}
    lines: list[str] = ["# 测试报告", "", "## 测试目的", ""]

    purpose = meta.get("purpose") or meta.get("description") or ""
    if purpose:
        lines.extend(_format_purpose_lines(str(purpose)))
    else:
        lines.append(f"验证测试计划 `{report.get('name', '')}` 的业务流程。")
    lines.append("")

    lines.append("测试结果：")
    if passed:
        lines.append("- ✅ 通过")
    else:
        summary = analysis.get("summary") or report.get("error") or "未通过"
        lines.append(f"- ❌ 未通过：{summary}")
    lines.extend(["", "---", "", "## 通信记录", ""])

    interactions = report.get("comm_interactions") or []
    if not interactions:
        lines.append("_（无串口 TX/RX 记录）_")
        lines.append("")
    else:
        for item in interactions:
            idx = item.get("index", 0)
            title = item.get("title") or f"交互 {idx}"
            lines.append(f"### 交互 {idx}：{title}")
            lines.append("")
            lines.append("```text")
            for frame in item.get("frames") or []:
                ts = frame.get("timestamp") or "--:--:--.---"
                direction = frame.get("dir") or "?"
                hex_val = frame.get("hex") or ""
                lines.append(f"[{direction}][{ts}]")
                lines.append(hex_val)
                lines.append("")
            lines.append("```")
            lines.append("")

    lines.extend(["---", "", "## 业务验证", ""])
    lines.extend(
        _render_business_verification(
            meta.get("expected_results"),
            report.get("steps") or [],
            passed=passed,
            analysis=analysis,
            interactions=interactions,
        )
    )
    lines.extend(["", "---", "", "## 结论", ""])
    if passed:
        lines.append("本次测试验证通过。")
    else:
        failed = analysis.get("failed_step")
        detail = analysis.get("summary") or report.get("error") or "存在失败步骤"
        if failed:
            lines.append(f"本次测试未通过：{detail}（失败步骤：{failed}）。")
        else:
            lines.append(f"本次测试未通过：{detail}。")
    lines.append("")
    return "\n".join(lines)


def group_comm_interactions(
    records: list[StepRecord],
    metadata: dict[str, Any],
    *,
    started_at: str = "",
) -> list[dict[str, Any]]:
    """Group serial send/wait-frame/request steps into business interactions."""
    expected_map = _expected_results_index(metadata.get("expected_results"))
    title_map = _report_interaction_titles(metadata.get("report_interactions"))
    ts_map = _step_end_timestamps(records, started_at)
    step_status = {r.id: r.status for r in records}
    interactions: list[dict[str, Any]] = []
    pending_tx: dict[str, Any] | None = None
    index = 0

    for record in records:
        ts = ts_map.get(record.id, "")
        action = record.action

        if action == "send":
            hx = _tx_hex_from_record(record)
            if hx:
                pending_tx = {
                    "dir": "TX",
                    "hex": hx,
                    "timestamp": ts,
                    "step_id": record.id,
                }
            continue

        if action in {"wait-frame", "wait_frame"}:
            frames: list[dict[str, Any]] = []
            if pending_tx:
                frames.append(pending_tx)
                pending_tx = None
            rx = _rx_hex_from_record(record)
            if rx:
                frames.append(
                    {"dir": "RX", "hex": rx, "timestamp": ts, "step_id": record.id}
                )
            if frames:
                index += 1
                interactions.append(
                    {
                        "index": index,
                        "title": _interaction_title(record.id, expected_map, title_map),
                        "step_id": record.id,
                        "status": step_status.get(record.id, ""),
                        "frames": frames,
                    }
                )
            continue

        if action == "request":
            frames = _request_frames(record, ts)
            if frames:
                index += 1
                interactions.append(
                    {
                        "index": index,
                        "title": _interaction_title(record.id, expected_map, title_map),
                        "step_id": record.id,
                        "status": step_status.get(record.id, ""),
                        "frames": frames,
                    }
                )
            pending_tx = None

    if pending_tx:
        index += 1
        interactions.append(
            {
                "index": index,
                "title": _interaction_title(pending_tx["step_id"], expected_map, title_map),
                "step_id": pending_tx["step_id"],
                "status": step_status.get(pending_tx["step_id"], ""),
                "frames": [pending_tx],
            }
        )

    return interactions


def _format_purpose_lines(purpose: str) -> list[str]:
    text = purpose.strip()
    if not text:
        return ["验证：", "- （未填写测试目的）"]
    lines = ["验证："]
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if any(ln.startswith(("-", "*", "•")) for ln in raw_lines):
        for ln in raw_lines:
            cleaned = ln.lstrip("-*• ").strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        return lines
    if len(raw_lines) == 1 and "。" in raw_lines[0]:
        parts = [p.strip() for p in raw_lines[0].split("。") if p.strip()]
        for part in parts:
            lines.append(f"- {part}。")
        return lines
    for ln in raw_lines:
        lines.append(f"- {ln}")
    return lines


def _render_business_verification(
    expected: Any,
    steps: list[dict[str, Any]],
    *,
    passed: bool,
    analysis: dict[str, Any],
    interactions: list[dict[str, Any]],
) -> list[str]:
    step_status = {s.get("id"): s.get("status") for s in steps if s.get("id")}
    lines: list[str] = []

    if isinstance(expected, list) and expected:
        for item in expected:
            if isinstance(item, dict):
                sid = str(item.get("step_id") or item.get("id") or "")
                desc = str(item.get("description") or item.get("desc") or sid or "业务检查点")
                ok = step_status.get(sid) == "ok"
                mark = "✅" if ok else "❌"
                lines.append(f"{mark} {desc}")
            else:
                mark = "✅" if passed else "❌"
                lines.append(f"{mark} {item}")
        return lines

    if interactions:
        for item in interactions:
            ok = item.get("status") == "ok"
            mark = "✅" if ok else "❌"
            lines.append(f"{mark} {item.get('title') or item.get('step_id')}")
        return lines

    mark = "✅" if passed else "❌"
    if passed:
        lines.append(f"{mark} 全部步骤执行成功")
    else:
        summary = analysis.get("summary") or "存在失败步骤"
        lines.append(f"{mark} {summary}")
    return lines


def _step_end_timestamps(records: list[StepRecord], started_at: str) -> dict[str, str]:
    if not started_at:
        return {}
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return {}
    offset_ms = 0
    out: dict[str, str] = {}
    for record in records:
        offset_ms += record.elapsed_ms
        end = start + timedelta(milliseconds=offset_ms)
        out[record.id] = end.strftime("%H:%M:%S.") + f"{end.microsecond // 1000:03d}"
    return out


def _expected_results_index(expected: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(expected, list):
        return out
    for item in expected:
        if not isinstance(item, dict):
            continue
        sid = item.get("step_id") or item.get("id")
        if sid:
            out[str(sid)] = item
    return out


def _report_interaction_titles(report_interactions: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(report_interactions, list):
        return out
    for item in report_interactions:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name")
        if not title:
            continue
        for key in ("wait_step", "step_id", "send_step", "id"):
            sid = item.get(key)
            if sid:
                out[str(sid)] = str(title)
    return out


def _interaction_title(
    step_id: str,
    expected_map: dict[str, dict[str, Any]],
    title_map: dict[str, str],
) -> str:
    if step_id in title_map:
        return title_map[step_id]
    if step_id in expected_map:
        desc = expected_map[step_id].get("description") or expected_map[step_id].get("desc")
        if desc:
            return str(desc)
    return _humanize_step_title(step_id)


def _humanize_step_title(step_id: str) -> str:
    loop_match = re.match(r"^(.+)\[(\d+)\]\.(.+)$", step_id)
    if loop_match:
        batch_no = int(loop_match.group(2)) + 1
        inner = _humanize_step_title(loop_match.group(3))
        return f"{inner}（第 {batch_no} 批）"
    short = step_id.rsplit(".", 1)[-1]
    for prefix in ("wait_", "send_", "build_"):
        if short.startswith(prefix):
            short = short[len(prefix):]
            break
    return short.replace("_", " ")


def _record_data(record: StepRecord) -> dict[str, Any]:
    result = record.result if isinstance(record.result, dict) else {}
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _tx_hex_from_record(record: StepRecord) -> str:
    data = _record_data(record)
    for key in ("sent", "hex", "frame_hex", "frame"):
        val = data.get(key)
        if val:
            return str(val)
    return ""


def _rx_hex_from_record(record: StepRecord) -> str:
    data = _record_data(record)
    val = data.get("frame_hex") or data.get("frame")
    return str(val) if val else ""


def _request_frames(record: StepRecord, timestamp: str) -> list[dict[str, Any]]:
    data = _record_data(record)
    frames: list[dict[str, Any]] = []
    request = data.get("request")
    response = data.get("response")
    if isinstance(request, dict) and request.get("frame_hex"):
        frames.append(
            {
                "dir": "TX",
                "hex": request["frame_hex"],
                "timestamp": timestamp,
                "step_id": record.id,
            }
        )
    if isinstance(response, dict) and response.get("frame_hex"):
        frames.append(
            {
                "dir": "RX",
                "hex": response["frame_hex"],
                "timestamp": timestamp,
                "step_id": record.id,
            }
        )
    return frames


def _serial_entry(record: StepRecord) -> dict[str, Any] | None:
    result = record.result if isinstance(record.result, dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}

    entry: dict[str, Any] = {
        "step_id": record.id,
        "action": record.action,
        "status": record.status,
        "elapsed_ms": record.elapsed_ms,
    }
    has_frame = False

    if record.action in {"serial.connect", "serial.open"} and data:
        port = data.get("port") or data.get("name")
        if port:
            entry["note"] = f"connect {port} baudrate={data.get('baudrate', '?')}"
            return entry

    if record.action == "send":
        tx = _tx_hex_from_record(record)
        if tx:
            entry["tx_hex"] = tx
            has_frame = True
    elif record.action in {"wait-frame", "wait_frame"}:
        rx = _rx_hex_from_record(record)
        if rx:
            entry["rx_hex"] = rx
            has_frame = True
        decoded = data.get("decoded") or data.get("values")
        if decoded:
            entry["decoded"] = decoded
            has_frame = True
    elif record.action == "build":
        tx = data.get("frame_hex") or data.get("frame") or data.get("hex")
        if tx:
            entry["tx_hex"] = tx
            has_frame = True
    else:
        if data.get("hex"):
            entry["tx_hex"] = data["hex"]
            has_frame = True
        if data.get("frame_hex") or data.get("frame"):
            entry["tx_hex"] = data.get("frame_hex") or data.get("frame")
            has_frame = True
        decoded = data.get("decoded") or data.get("values")
        if decoded:
            entry["decoded"] = decoded
            has_frame = True

    request = data.get("request")
    response = data.get("response")
    if isinstance(request, dict):
        if request.get("frame_hex"):
            entry["tx_hex"] = request["frame_hex"]
            has_frame = True
        if request.get("decoded"):
            entry["tx_decoded"] = request["decoded"]
            has_frame = True
    if isinstance(response, dict):
        if response.get("frame_hex"):
            entry["rx_hex"] = response["frame_hex"]
            has_frame = True
        if response.get("decoded"):
            entry["rx_decoded"] = response["decoded"]
            has_frame = True

    if detail.get("last_decoded"):
        entry["last_decoded"] = detail["last_decoded"]
        has_frame = True
    if detail.get("received_frames") is not None:
        entry["received_frames"] = detail["received_frames"]
        has_frame = True

    if record.action == "wait-frame" and data.get("matched") is not None:
        entry["note"] = f"matched={data.get('matched')}"
        has_frame = True

    return entry if has_frame or entry.get("note") else None


def _match_expected(expected: Any, step_id: str) -> Any:
    if not isinstance(expected, list):
        return None
    for item in expected:
        if isinstance(item, dict) and item.get("step_id") == step_id:
            return item
        if isinstance(item, dict) and item.get("id") == step_id:
            return item
    return None


def _recommendations(code: str, error: RunError, records: list[StepRecord]) -> list[str]:
    recs: list[str] = []
    if code == WAIT_FRAME_TIMEOUT:
        recs.append("查看 execution_report serial_trace 与 frames.log 对比最后一帧")
    if code == MATCH_FAILED and error.details.get("mismatch_summary"):
        recs.append("根据 mismatch_summary 调整 wait-frame expect 或 mock 响应帧")
    failed_idx = next((i for i, r in enumerate(records) if r.id == error.step_id), -1)
    if failed_idx > 0:
        prev = records[failed_idx - 1]
        if prev.action in {"send", "request", "build"}:
            recs.append(f"失败前一步 {prev.id}({prev.action}) 已执行，检查其输出帧是否正确")
    return recs


def write_execution_report_files(
    ctx: Any,
    plan: dict[str, Any],
    *,
    status: str,
    error_text: str = "",
    primary_error: RunError | None = None,
    total_ms: int = 0,
) -> dict[str, Any]:
    """Write execution_report.json and .md into ctx.report_dir."""
    report = build_execution_report(
        ctx=ctx,
        plan=plan,
        status=status,
        error_text=error_text,
        primary_error=primary_error,
        total_ms=total_ms,
    )
    report_dir = Path(ctx.report_dir)
    json_path = report_dir / "execution_report.json"
    md_path = report_dir / "execution_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_execution_report_md(report), encoding="utf-8")
    return report
