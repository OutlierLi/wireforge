#!/usr/bin/env python3
"""执行配对串口 TestPlan YAML（先确保已 generate）。

用法:
  python3 scripts/generate_pair_serial_plans.py
  python3 scripts/run_pair_serial_test.py --proto csg --port mock://auto
  python3 scripts/run_pair_serial_test.py --proto csg --port /dev/ttyUSB0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from test_runner.exec_command import ExecCommand, ExecOptions

RUNS = _PROJECT_ROOT / "database" / "runs"
_PLAN = {
    "csg": RUNS / "csg_pair_serial.yaml",
    "dlt645": RUNS / "dlt645_pair_serial.yaml",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="exec_test 执行 pairing 串口 TestPlan")
    parser.add_argument("--proto", choices=["csg", "dlt645"], required=True)
    parser.add_argument("--port", default="mock://auto")
    parser.add_argument("--conn", default="pair_test")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--wait-timeout-ms", type=int, default=5000)
    parser.add_argument("--pair-id", help="单条 pairing 时使用 generate 输出的独立文件")
    parser.add_argument("--generate", action="store_true", help="执行前重新 generate")
    args = parser.parse_args(argv)

    if args.generate or not _PLAN[args.proto].exists():
        from scripts.generate_pair_serial_plans import generate

        generate(proto_key=args.proto, pair_id=args.pair_id)

    if args.pair_id:
        plan_file = RUNS / f"{args.proto}_pair_serial_{args.pair_id}.yaml"
    else:
        plan_file = _PLAN[args.proto]

    if not plan_file.exists():
        print(f"plan not found: {plan_file}", file=sys.stderr)
        return 1

    result = ExecCommand.run(
        file=str(plan_file),
        options=ExecOptions(
            vars={
                "port": args.port,
                "conn": args.conn,
                "baudrate": args.baudrate,
                "wait_timeout_ms": args.wait_timeout_ms,
            },
        ),
    )
    ok = result.get("ok") or result.get("status") == "success"
    if result.get("report_dir"):
        print(f"Report: {result['report_dir']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
