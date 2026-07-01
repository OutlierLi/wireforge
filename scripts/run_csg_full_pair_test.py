#!/usr/bin/env python3
"""CSG 2016 请求-响应配对全量 Build/Decode 测试。

用法:
  python3 scripts/run_csg_full_pair_test.py
  python3 scripts/run_csg_full_pair_test.py --pair-id afn02_add_task
  python3 scripts/run_csg_full_pair_test.py --fail-fast -q
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from protocol_tool.compiler.pipeline import compile_protocol
from protocol_tool.ir.nodes import ProtocolIR
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import BuildEngine, DecodeEngine

from tests.csg_pair_catalog import (
    format_pair_di_chain,
    iter_pair_scenario_messages,
    iter_pair_scenarios,
    load_csg_pairs,
    serial_trace_lines,
    validate_table4_coverage,
)
from tests.protocol_build_utils import MessageTestResult, run_pair_message
from tests.protocol_info import CSG_FIELD_DEFAULTS

LOG_ROOT = _PROJECT_ROOT / "log" / "csg_full_test"
REGISTRY = str(_PROJECT_ROOT / "protocol_tool" / "protocols" / "registry.yaml")
COMPILED_DIR = str(_PROJECT_ROOT / "compiled")


def run_all_pairs(
    *,
    pair_id: str | None = None,
    fail_fast: bool = False,
    quiet: bool = False,
    log_dir: Path | None = None,
) -> tuple[int, dict]:
    """执行全量配对测试，写入 log/csg_full_test/<run_id>/。"""
    pairs_data = load_csg_pairs()
    missing = validate_table4_coverage(pairs_data)
    if missing:
        raise SystemExit(f"pairs yaml missing table4 downlink entries: {missing}")

    compile_protocol(REGISTRY, "csg_2016", output_dir=COMPILED_DIR)
    ir = ProtocolIR.from_json_file(f"{COMPILED_DIR}/csg_2016.ir.json")
    codecs = create_builtin_registry()
    build_engine = BuildEngine(ir, codecs)
    decode_engine = DecodeEngine(ir, codecs)
    defaults = dict(CSG_FIELD_DEFAULTS)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = log_dir or (LOG_ROOT / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "full_test.log"
    serial_trace_path = out_dir / "serial_trace.log"
    summary_path = out_dir / "summary.json"
    failures_path = out_dir / "failures.json"

    results: list[MessageTestResult] = []
    pair_summaries: list[dict] = []
    all_serial_lines: list[str] = []

    with open(log_path, "w", encoding="utf-8") as log_file:
        def emit(line: str = ""):
            if not quiet:
                print(line)
            log_file.write(line + "\n")
            log_file.flush()

        emit("=" * 70)
        emit(f"  CSG 全量配对 Build/Decode 测试  run_id={run_id}")
        emit("=" * 70)

        for pair in pairs_data["pairs"]:
            pid = pair["id"]
            if pair_id and pid != pair_id:
                continue

            emit(f"\n--- pair: {pid} ---")
            pair_results: list[MessageTestResult] = []
            pair_failed = False
            scenario_summaries: list[dict] = []

            for scenario in iter_pair_scenarios(pair):
                scenario_id = scenario["id"]
                di_chain = format_pair_di_chain(pair, scenario_id)
                emit(f"  scenario: {scenario_id}")
                emit(f"  chain: {di_chain}")
                scenario_results: list[MessageTestResult] = []

                for msg in iter_pair_scenario_messages(pair, scenario_id):
                    result = run_pair_message(msg, ir, build_engine, decode_engine, defaults)
                    scenario_results.append(result)
                    pair_results.append(result)
                    results.append(result)

                    label = f"{pid}/{scenario_id}/{msg.slot} AFN={msg.afn} DI={msg.di} {msg.dir}"
                    if result.status == "PASS":
                        emit(f"  [PASS] {label}")
                        if not quiet:
                            emit(f"        {result.path_str}")
                            emit(f"        {result.frame_hex}")
                    else:
                        emit(f"  [FAIL] {label} | {result.error}")
                        pair_failed = True
                        if fail_fast:
                            break

                scenario_pair = dict(pair)
                scenario_pair["response_scenarios"] = [scenario]
                trace = serial_trace_lines(scenario_pair, scenario_results)
                if trace:
                    emit("  serial:")
                    for line in trace:
                        emit(f"    {line}")

                all_serial_lines.append(f"=== {pid}/{scenario_id} ===")
                all_serial_lines.append(f"chain: {di_chain}")
                all_serial_lines.extend(trace)
                all_serial_lines.append("")
                scenario_summaries.append({
                    "id": scenario_id,
                    "di_chain": di_chain,
                    "serial_trace": trace,
                    "messages": [r.to_dict() for r in scenario_results],
                    "failed": sum(1 for r in scenario_results if r.status == "FAIL"),
                    "passed": sum(1 for r in scenario_results if r.status == "PASS"),
                })

                if fail_fast and pair_failed:
                    break

            pair_summaries.append({
                "id": pid,
                "scenarios": scenario_summaries,
                "messages": [r.to_dict() for r in pair_results],
                "failed": sum(1 for r in pair_results if r.status == "FAIL"),
                "passed": sum(1 for r in pair_results if r.status == "PASS"),
            })
            if fail_fast and pair_failed:
                break

    with open(serial_trace_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_serial_lines).rstrip() + "\n")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    summary = {
        "run_id": run_id,
        "pair_count": len(pair_summaries),
        "message_count": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pairs": pair_summaries,
        "log_dir": str(out_dir),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    failures = [r.to_dict() for r in results if r.status == "FAIL"]
    with open(failures_path, "w", encoding="utf-8") as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)

    if not quiet:
        print(f"\nSummary: {passed} pass, {failed} fail, {skipped} skip")
        print(f"Log: {out_dir}")

    return (1 if failed else 0, summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CSG 配对全量 build/decode 测试")
    parser.add_argument("--pair-id", help="仅运行指定 pair id")
    parser.add_argument("--fail-fast", action="store_true", help="首次失败即停止")
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式（仍写日志）")
    args = parser.parse_args(argv)

    rc, _ = run_all_pairs(
        pair_id=args.pair_id,
        fail_fast=args.fail_fast,
        quiet=args.quiet,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
