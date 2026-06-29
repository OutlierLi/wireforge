"""Execution test report — structured template for real serial runs."""

from __future__ import annotations

import json
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
        "then 使用 dict 格式: command + args.hex",
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
    env = report.get("environment") or {}
    summary = report.get("execution_summary") or {}
    lines: list[str] = [
        f"# 执行测试报告 — {report.get('name', '')}",
        "",
        f"- **Run ID**: `{report.get('run_id', '')}`",
        f"- **状态**: {report.get('status', '')}",
        f"- **耗时**: {report.get('elapsed_ms', 0)} ms",
        f"- **开始时间**: {report.get('started_at', '')}",
        "",
    ]

    if meta.get("purpose"):
        lines.extend(["## 测试目的", "", str(meta["purpose"]), ""])
    if meta.get("description"):
        lines.extend(["## 描述", "", str(meta["description"]), ""])
    if meta.get("test_flow"):
        lines.extend(["## 测试流程", ""])
        flow = meta["test_flow"]
        if isinstance(flow, str):
            lines.append(flow)
        elif isinstance(flow, list):
            for i, item in enumerate(flow, 1):
                lines.append(f"{i}. {item}")
        lines.append("")

    expected = meta.get("expected_results")
    if expected:
        lines.extend(["## 预期结果", ""])
        if isinstance(expected, list):
            for item in expected:
                if isinstance(item, dict):
                    sid = item.get("step_id") or item.get("id") or "?"
                    desc = item.get("description") or item.get("desc") or ""
                    lines.append(f"- **{sid}**: {desc}")
                    if item.get("expect"):
                        lines.append(f"  - expect: `{json.dumps(item['expect'], ensure_ascii=False)}`")
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(str(expected))
        lines.append("")

    vars_ = env.get("vars") or {}
    if vars_:
        lines.extend(["## 执行环境", ""])
        for key in ("port", "conn", "baudrate", "proto"):
            if key in vars_:
                lines.append(f"- **{key}**: `{vars_[key]}`")
        lines.append("")

    trace = report.get("serial_trace") or []
    lines.extend(["## 串口收发记录", ""])
    if not trace:
        lines.append("_（无 send/wait-frame/request/build 帧记录）_")
    else:
        for entry in trace:
            lines.append(f"### {entry.get('step_id')} ({entry.get('action')})")
            if entry.get("tx_hex"):
                lines.append(f"- **TX**: `{entry['tx_hex']}`")
            if entry.get("rx_hex"):
                lines.append(f"- **RX**: `{entry['rx_hex']}`")
            if entry.get("decoded"):
                lines.append(f"- **解码**: `{json.dumps(entry['decoded'], ensure_ascii=False)}`")
            if entry.get("note"):
                lines.append(f"- {entry['note']}")
            lines.append("")

    lines.extend(["## 步骤执行结果", ""])
    for step in report.get("steps") or []:
        mark = "OK" if step.get("status") == "ok" else "FAIL"
        err = f" — {step['error']}" if step.get("error") else ""
        lines.append(
            f"- [{mark}] `{step.get('id')}` ({step.get('action')}) "
            f"{step.get('elapsed_ms', 0)}ms{err}"
        )
    lines.append("")

    analysis = report.get("error_analysis") or {}
    if report.get("status") != "success":
        lines.extend(["## 错误分析", ""])
        lines.append(f"**摘要**: {analysis.get('summary', report.get('error') or 'unknown')}")
        if analysis.get("code"):
            lines.append(f"**错误码**: `{analysis['code']}`")
        if analysis.get("failed_step"):
            lines.append(f"**失败步骤**: `{analysis['failed_step']}`")
        for key in ("mismatch_summary", "received_frames", "last_decoded"):
            if analysis.get(key) is not None:
                lines.append(f"- **{key}**: `{json.dumps(analysis[key], ensure_ascii=False)}`")
        hints = analysis.get("hints") or []
        recs = analysis.get("recommendations") or []
        if hints or recs:
            lines.append("")
            lines.append("**排查建议**:")
            for hint in hints + recs:
                lines.append(f"- {hint}")
        lines.append("")

    lines.append(f"_报告目录: `{report.get('report_dir', '')}`_")
    lines.append("")
    return "\n".join(lines)


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

    if data.get("frame_hex") or data.get("frame"):
        entry["tx_hex"] = data.get("frame_hex") or data.get("frame")
        has_frame = True
    if data.get("hex"):
        entry["tx_hex"] = data["hex"]
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
