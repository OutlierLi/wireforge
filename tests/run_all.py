#!/usr/bin/env python3
"""全量测试 — pytest 单元测试 + check.py 往返验证 + TUI batch 测试。

用法: python3 tests/run_all.py
"""

import subprocess, sys, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 确保能 import console 模块
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


# 1. 单元测试 + 命令行 + auto_rule + var (all pytest)
run_step("1/4 pytest 全量", [
    sys.executable, "-m", "pytest",
    "tests/test_codecs.py", "tests/test_compiler.py",
    "tests/test_runtime.py", "tests/test_cli.py",
    "tests/test_console.py", "tests/test_auto_rule.py",
    "tests/test_upg.py",
    "-v", "--tb=short",
])

# 2. 往返验证 (check.py)
run_step("2/4 Build→Decode 往返验证", [
    sys.executable, "tests/check.py",
])

# 3. /var 命令 NDJSON 集成测试
def test_var_ndjson():
    """通过 NDJSON 管道测试 /var 全部子命令。"""
    global failures
    print(f"\n{'='*60}")
    print(f"  3/4 /var NDJSON 集成测试")
    print(f"{'='*60}")

    requests = [
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"clear"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["proto"],"value":"csg"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["afn"],"value":"03"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["count"],"value":"5","type":"integer"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["frame"],"value":"68 01 02","type":"hex"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["payload"],"value":"{\"k\":\"v\"}","type":"json"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"get","_":["proto"]}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"show"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"show","json":True}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"export","file":"/tmp/wf_run_all_vars.yaml"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"clear"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"import","file":"/tmp/wf_run_all_vars.yaml"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"delete","_":["count"]}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"get","_":["nonexistent"]}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"clear"}},
    ]
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "console.ndjson"],
        input=payload, capture_output=True, text=True,
        timeout=15, cwd=str(ROOT),
    )
    lines = [l.strip() for l in proc.stdout.strip().split("\n") if l.strip()]
    results = [json.loads(l) for l in lines]

    checks = 0
    passed = 0
    # 1: clear → success
    assert results[0]["status"] == "success", f"clear failed: {results[0]}"
    passed += 1; checks += 1
    # 2-5: set → success
    for i in range(1, 6):
        assert results[i]["status"] == "success", f"set[{i}] failed: {results[i]}"
        passed += 1; checks += 1
    # 6: get proto → success, value=csg
    assert results[6]["status"] == "success"
    assert results[6]["data"]["value"] == "csg"
    passed += 1; checks += 1
    # 7: show → success, count>=4
    assert results[7]["status"] == "success"
    assert results[7]["data"]["count"] >= 4
    passed += 1; checks += 1
    # 8: show --json → success
    assert results[8]["status"] == "success"
    passed += 1; checks += 1
    # 9: export → success, count>=4
    assert results[9]["status"] == "success"
    assert results[9]["data"]["count"] >= 4
    passed += 1; checks += 1
    # 10: clear → success
    assert results[10]["status"] == "success"
    passed += 1; checks += 1
    # 11: import → success, count>=4
    assert results[11]["status"] == "success"
    assert results[11]["data"]["count"] >= 4
    passed += 1; checks += 1
    # 12: delete → success
    assert results[12]["status"] == "success"
    passed += 1; checks += 1
    # 13: get nonexistent → execution_error
    assert results[13]["status"] == "execution_error"
    assert "不存在" in results[13].get("error", "")
    passed += 1; checks += 1
    # 14: clear → success
    assert results[14]["status"] == "success"
    passed += 1; checks += 1

    print(f"  ✓ {passed}/{checks} NDJSON checks passed")
    # cleanup
    try: os.remove("/tmp/wf_run_all_vars.yaml")
    except OSError: pass

try:
    test_var_ndjson()
except Exception as e:
    failures += 1
    print(f"  ✗ FAILED: {e}")


# 4. /var 变量引用 + build 联动测试
def test_var_build_integration():
    """通过 exec_cmd 测试 var → build 变量引用联动。"""
    global failures
    print(f"\n{'='*60}")
    print(f"  4/4 /var → build 联动测试")
    print(f"{'='*60}")

    from console.api import exec_cmd
    from console.variable_store import store

    store.clear()
    exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "dlt645"})
    exec_cmd("var", {"sub": "set", "_": ["func_val"], "value": "0x11"})
    exec_cmd("var", {"sub": "set", "_": ["di_val"], "value": "00010000"})

    from console.runtime import runtime
    args = {"proto": "${proto}", "func": "${func_val}", "di": "${di_val}", "dir": "downlink"}
    resolved = runtime._resolve_var_refs(args)
    assert resolved["proto"] == "dlt645"
    assert resolved["func"] == "0x11"
    assert resolved["di"] == "00010000"

    r = exec_cmd("build", resolved)
    assert r["status"] == "success", f"build failed: {r}"
    assert r["data"].get("frame"), "should have frame"

    # 验证 last_build 自动设置
    lb = store.get_value("last_build")
    assert lb is not None
    lf = store.get_value("last_frame")
    assert lf is not None

    store.clear()
    print("  ✓ var → build 联动 + last_build/last_frame")

try:
    test_var_build_integration()
except Exception as e:
    failures += 1
    print(f"  ✗ FAILED: {e}")


print(f"\n{'='*60}")
if failures:
    print(f"  {failures} step(s) FAILED")
else:
    print(f"  ALL tests PASSED")
print(f"{'='*60}")
sys.exit(failures)
