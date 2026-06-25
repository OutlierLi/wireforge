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

    # ── /print 测试 ──
    print_reqs = [
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["p"],"value":"csg"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["a"],"value":"03"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"set","_":["f"],"value":"68 01","type":"hex"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/print","args":{"text":"协议：${p}"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/print","args":{"text":"${f}"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/print","args":{"text":"文本：${p}","raw":True}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/print","args":{"text":"未知：${no}保持不变"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/var","args":{"sub":"clear"}},
    ]
    p_payload = "\n".join(json.dumps(r) for r in print_reqs) + "\n"
    p_proc = subprocess.run(
        [sys.executable, "-m", "console.ndjson"],
        input=p_payload, capture_output=True, text=True,
        timeout=15, cwd=str(ROOT),
    )
    p_lines = [l.strip() for l in p_proc.stdout.strip().split("\n") if l.strip()]
    p_results = [json.loads(l) for l in p_lines]
    # set×3 → success
    for i in range(3):
        assert p_results[i]["status"] == "success", f"print setup[{i}] failed"
        passed += 1; checks += 1
    # print "协议：${p}" → "协议：csg"
    assert p_results[3]["data"]["output"] == "协议：csg"
    passed += 1; checks += 1
    # print "${f}" → "68 01"
    assert p_results[4]["data"]["output"] == "68 01"
    passed += 1; checks += 1
    # print --raw → literal "${p}"
    assert p_results[5]["data"]["output"] == "文本：${p}"
    assert p_results[5]["data"]["raw"] is True
    passed += 1; checks += 1
    # print unknown → preserved
    assert p_results[6]["data"]["output"] == "未知：${no}保持不变"
    passed += 1; checks += 1
    # clear → success
    assert p_results[7]["status"] == "success"
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


# 4. /var → /print → /build 变量联动测试
def test_var_print_build():
    """通过 exec_cmd 测试 var → print → build 变量引用联动。"""
    global failures
    print(f"\n{'='*60}")
    print(f"  4/4 /var → print → build 联动测试")
    print(f"{'='*60}")

    from console.api import exec_cmd
    from console.variable_store import store

    store.clear()
    exec_cmd("var", {"sub": "set", "_": ["proto"], "value": "dlt645"})
    exec_cmd("var", {"sub": "set", "_": ["func_val"], "value": "0x11"})
    exec_cmd("var", {"sub": "set", "_": ["di_val"], "value": "00010000"})

    # print 引用测试
    r = exec_cmd("print", {"text": "proto=${proto} func=${func_val}"})
    assert r["status"] == "success"
    assert r["data"]["output"] == "proto=dlt645 func=0x11"
    print(f"  ✓ print: {r['data']['output']}")

    # /print --raw
    r = exec_cmd("print", {"text": "raw:${proto}", "raw": True})
    assert r["data"]["output"] == "raw:${proto}"
    print(f"  ✓ print --raw: {r['data']['output']}")

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
    print("  ✓ var → print → build 联动 + last_build/last_frame")

try:
    test_var_print_build()
except Exception as e:
    failures += 1
    print(f"  ✗ FAILED: {e}")


# 5. /build --from-frame 集成测试
def test_build_from_frame():
    """通过 NDJSON 测试 --from-frame decode → rebuild → --set 完整流程。"""
    global failures
    print(f"\n{'='*60}")
    print(f"  5/5 /build --from-frame 集成测试")
    print(f"{'='*60}")

    from console.api import exec_cmd
    from console.variable_store import store

    # 645 读数据应答帧
    hex_645 = "FE FE FE FE 68 01 00 00 00 00 00 68 91 08 33 33 34 33 59 39 54 53 70 16"
    # CSG 查询厂商帧
    hex_csg = "68 0C 00 40 03 01 01 03 00 E8 30 16"
    # 645 读地址帧
    hex_addr = "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16"

    checks = 0
    passed = 0

    # 1. from-frame 重建相同帧 (645)
    r = exec_cmd("build", {"from_frame": hex_645})
    assert r["status"] == "success", f"645 rebuild: {r.get('error','')}"
    assert r["data"]["frame"] == hex_645, f"frame mismatch"
    passed += 1; checks += 1
    print(f"  ✓ 645 rebuild identical")

    # 2. from-frame 重建相同帧 (CSG)
    r = exec_cmd("build", {"from_frame": hex_csg})
    assert r["status"] == "success"
    assert r["data"]["frame"] == hex_csg
    passed += 1; checks += 1
    print(f"  ✓ CSG rebuild identical")

    # 3. from-frame --set 修改字段
    r = exec_cmd("build", {"from_frame": hex_645, "set": "freeze_year=27"})
    assert r["status"] == "success"
    assert r["data"]["frame"] != hex_645, "should differ after --set"
    passed += 1; checks += 1
    print(f"  ✓ --set freeze_year=27 changed frame")

    # 4. from-frame --resolve
    r = exec_cmd("build", {"from_frame": hex_645, "resolve": True})
    assert r["status"] == "success"
    assert "decoded_values" in r["data"]
    assert r["data"]["decoded_values"]["freeze_month"] == "06"
    passed += 1; checks += 1
    print(f"  ✓ --resolve returns decoded_values")

    # 5. from-frame 读地址帧
    r = exec_cmd("build", {"from_frame": hex_addr})
    assert r["status"] == "success"
    assert r["data"]["frame"] == hex_addr
    passed += 1; checks += 1
    print(f"  ✓ read-address frame")

    # 6. from-frame 显式协议
    r = exec_cmd("build", {"from_frame": hex_645, "proto": "dlt645"})
    assert r["status"] == "success"
    passed += 1; checks += 1
    print(f"  ✓ explicit proto")

    # 7. from-frame 非法 hex
    r = exec_cmd("build", {"from_frame": "ZZ ZZ"})
    assert r["status"] != "success"
    passed += 1; checks += 1
    print(f"  ✓ invalid hex rejected")

    # 8. from-frame + var 联动：解码后存为变量再修改
    store.clear()
    r = exec_cmd("build", {"from_frame": hex_645})
    frame_val = r["data"]["frame"]
    # 存为变量
    exec_cmd("var", {"sub": "set", "_": ["saved_frame"], "value": frame_val, "type": "hex"})
    # 用 from-frame + --set 修改
    r2 = exec_cmd("build", {"from_frame": frame_val, "set": "freeze_month=12"})
    assert r2["status"] == "success"
    assert r2["data"]["frame"] != frame_val, "should differ"
    passed += 1; checks += 1
    print(f"  ✓ var → from-frame → --set chain")

    store.clear()
    print(f"  ✓ {passed}/{checks} checks passed")

try:
    test_build_from_frame()
except Exception as e:
    failures += 1
    print(f"  ✗ FAILED: {e}")


# 6. /delay 集成测试
def test_delay():
    """通过 NDJSON 测试 /delay ms/s。"""
    global failures
    print(f"\n{'='*60}")
    print(f"  6/6 /delay 集成测试")
    print(f"{'='*60}")

    delay_reqs = [
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/delay","args":{"value":"50ms"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/delay","args":{"value":"0.1s"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/delay","args":{"value":"50"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/delay","args":{"value":"abc"}},
        {"schema":"protocol-tui.v1","type":"command.execute","command":"/delay","args":{"value":"301s"}},
    ]
    payload = "\n".join(json.dumps(r) for r in delay_reqs) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "console.ndjson"],
        input=payload, capture_output=True, text=True,
        timeout=15, cwd=str(ROOT),
    )
    lines = [l.strip() for l in proc.stdout.strip().split("\n") if l.strip()]
    results = [json.loads(l) for l in lines]

    checks = passed = 0
    # 50ms → success
    assert results[0]["status"] == "success"; passed += 1; checks += 1
    assert results[0]["data"]["elapsed_ms"] >= 20; passed += 1; checks += 1
    # 0.1s → success
    assert results[1]["status"] == "success"; passed += 1; checks += 1
    assert results[1]["data"]["seconds"] == 0.1; passed += 1; checks += 1
    # 50 (default ms) → success
    assert results[2]["status"] == "success"; passed += 1; checks += 1
    # abc → fail
    assert results[3]["status"] != "success"; passed += 1; checks += 1
    # 301s → fail (exceeds max)
    assert results[4]["status"] != "success"; passed += 1; checks += 1

    print(f"  ✓ {passed}/{checks} checks passed")

try:
    test_delay()
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
