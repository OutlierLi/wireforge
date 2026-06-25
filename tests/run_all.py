#!/usr/bin/env python3
"""全量测试 — pytest 单元测试 + check.py 往返验证。

用法: python3 tests/run_all.py
"""

import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = 0


def run_step(title: str, cmd: list[str]):
    global failures
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        failures += 1
        print(f"  ✗ FAILED (exit {r.returncode})")
    else:
        print(f"  ✓ PASSED")


# 1. 单元测试 + 命令行 + auto_rule (all pytest)
run_step("1/3 pytest 全量", [
    sys.executable, "-m", "pytest",
    "tests/test_codecs.py", "tests/test_compiler.py",
    "tests/test_runtime.py", "tests/test_cli.py",
    "tests/test_console.py", "tests/test_auto_rule.py",
    "tests/test_upg.py",
    "-v", "--tb=short",
])

# 2. 往返验证 (check.py)
run_step("2/2 Build→Decode 往返验证", [
    sys.executable, "tests/check.py",
])


print(f"\n{'='*60}")
if failures:
    print(f"  {failures} step(s) FAILED")
else:
    print(f"  ALL {92 + 85} tests PASSED")
print(f"{'='*60}")
sys.exit(failures)
