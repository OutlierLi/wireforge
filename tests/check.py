#!/usr/bin/env python3
"""
项目健康检查 — 编译 → 往返测试 → 路由图

通用逻辑: protocol_info.py 提供报文事实 → resolve_path 找唯一路径 → build 生成字节流 → decode 验证
CSG 和 645 共用同一套流程，由 protocol_info 驱动。

用法:  python3 tests/check.py
"""

import sys, json, random
from pathlib import Path
from datetime import datetime

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

_OUT = _project_root / "tests" / "check_output"
_OUT.mkdir(parents=True, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_log_path = _OUT / f"check_{ts}.log"
_log_file = open(_log_path, "w", encoding="utf-8")

def log(msg: str):
    print(msg)
    _log_file.write(msg + "\n")
    _log_file.flush()


# ═══════════════════════════════════════════════════════════════
# 通用 Build + Decode
# ═══════════════════════════════════════════════════════════════

from tests.protocol_build_utils import auto_fill_leaf_fields


def run_protocol_tests(proto, ir, build_engine, decode_engine, counters, failures):
    """通用测试：遍历 protocol_info，resolve_path → build → decode"""
    from tests.protocol_info import (
        DLT645_MESSAGES, DLT645_DI_VARIANTS, DLT645_FIELD_DEFAULTS,
        CSG_MESSAGES, CSG_FIELD_DEFAULTS,
    )

    addr = "000000000001"
    addr2 = "000000000002"   # 第二条报文需要另一个地址时使用
    now = datetime.now()
    t6 = now.strftime("%y%m%d%H%M%S")
    t5 = now.strftime("%y%m%d%H%M")

    if proto == "dlt645_2007":
        msgs = DLT645_MESSAGES
        defaults = dict(DLT645_FIELD_DEFAULTS)

        for msg in msgs:
            func = msg["func"]
            desc = msg["description"]
            direction = msg["direction"]

            for dir_val, dir_name in [(0, "downlink"), (1, "uplink")]:
                if direction not in ("both", dir_name):
                    continue

                info = {"func": func, "direction": dir_name}
                # 对双向报文的上行方向，加上默认 DI (如 read_data_response 需要 di)
                if direction == "both" and dir_val == 1 and "di" in (msg.get("response_fields", [])):
                    info["di"] = defaults.get("di", "00010000")
                try:
                    path = build_engine.resolve_path(info)
                except ValueError as e:
                    counters["fail"] += 1
                    failures.append(f"dlt645_{msg['name']}_{dir_name}: {e}")
                    log(f"    ✗ {desc:20s}({dir_name[:4]:4s}) path error: {e}")
                    continue

                leaf = ir.leaves.get(path["leaf_id"])
                # 帧级默认值: 前导码取 IR 中定义的默认值
                preamble_default = 0
                for ff in ir.frame.fields:
                    if ff.name == "preamble":
                        preamble_default = ff.params.get("default", ff.params.get("min", 0))
                        break
                fv = {"preamble": preamble_default, "address": addr}
                # 请求和应答可分别指定帧默认值 (如读地址请求用广播地址 AA...AA, 应答用实际地址)
                if dir_val == 0 and "frame_defaults" in msg:
                    fv.update(msg["frame_defaults"])
                if dir_val == 1:
                    if "response_frame_defaults" in msg:
                        fv.update(msg["response_frame_defaults"] or {})
                fv["control"] = {"func": func, "dir": dir_val, "ack": 0, "follow": 0}
                # 自动填充 leaf 需要的字段 (类型感知: struct 用 _struct 后缀)
                field_names = (msg.get("request_fields", []) if dir_val == 0
                              else msg.get("response_fields", []))
                for fn in field_names:
                    if fn in fv:
                        continue
                    # Check leaf field type for struct fields
                    lf_type = None
                    for lf in leaf.fields:
                        if lf.name == fn:
                            lf_type = lf.type_ref; break
                    if lf_type == "struct" and fn + "_struct" in defaults:
                        fv[fn] = defaults[fn + "_struct"]
                    elif fn in defaults:
                        fv[fn] = defaults[fn]
                fv = auto_fill_leaf_fields(leaf, defaults, fv, ir)

                try:
                    r = build_engine.build(fv, info=info)
                    decode_engine.decode(r.frame)
                    counters["pass"] += 1
                    log(f"    ✓ {desc:20s}({dir_name[:4]:4s}) {r.path_str}")
                    log(f"      {r.frame_hex}")
                except Exception as e:
                    counters["fail"] += 1
                    failures.append(f"dlt645_{msg['name']}_{dir_name}: {e}")
                    log(f"    ✗ {desc:20s}({dir_name[:4]:4s}) build error: {e}")

        # DI 变体
        for di_hex, di_desc, di_fields in DLT645_DI_VARIANTS:
            info = {"func": 0x11, "direction": "uplink", "di": di_hex}
            try:
                path = build_engine.resolve_path(info)
                leaf = ir.leaves.get(path["leaf_id"])
                fv = {"preamble": 1, "address": addr,
                      "control": {"func": 0x11, "dir": 1, "ack": 0, "follow": 0},
                      "di": di_hex}
                for fn in di_fields:
                    if fn in defaults:
                        fv[fn] = defaults[fn]
                fv = auto_fill_leaf_fields(leaf, defaults, fv, ir)
                r = build_engine.build(fv, info=info)
                decode_engine.decode(r.frame)
                counters["pass"] += 1
                log(f"    ✓ DI={di_hex} {di_desc:20s} {r.path_str}")
                log(f"      {r.frame_hex}")
            except Exception as e:
                counters["fail"] += 1
                failures.append(f"dlt645_DI_{di_hex}: {e}")
                log(f"    ✗ DI={di_hex} {di_desc:20s} {e}")

    elif proto == "csg_2016":
        msgs = CSG_MESSAGES
        defaults = dict(CSG_FIELD_DEFAULTS)

        for msg in msgs:
            desc = msg["description"]
            info = {"afn": msg["afn"], "di": msg["di"],
                    "direction": msg["direction"], "has_address": msg["has_address"]}

            try:
                path = build_engine.resolve_path(info)
            except ValueError as e:
                counters["fail"] += 1
                failures.append(f"csg_{msg['name']}: {e}")
                log(f"    ✗ {desc:25s} path error: {e}")
                continue

            leaf = ir.leaves.get(path["leaf_id"])
            fv = {"afn": msg["afn"], "seq": 1, "di": msg["di"]}
            # 地址域
            if msg["has_address"]:
                fv["address_area"] = {"asrc": addr, "adst": "000000000000"}
            # 字段值
            for fn in (msg.get("request_fields", []) + msg.get("response_fields", [])):
                if fn in defaults:
                    fv[fn] = defaults[fn]
            fv = auto_fill_leaf_fields(leaf, defaults, fv, ir)

            try:
                r = build_engine.build(fv, info=info)
                decode_engine.decode(r.frame)
                counters["pass"] += 1
                log(f"    ✓ {desc:25s} {r.path_str}")
                log(f"      {r.frame_hex}")
            except Exception as e:
                counters["fail"] += 1
                failures.append(f"csg_{msg['name']}: {e}")
                log(f"    ✗ {desc:25s} build error: {e}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

from protocol_tool.compiler.pipeline import compile_protocol
from protocol_tool.ir.nodes import ProtocolIR
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import BuildEngine, DecodeEngine
from protocol_tool.utils.graph import generate_svg

registry = str(_project_root / "protocol_tool" / "protocols" / "registry.yaml")
compiled_dir = str(_project_root / "compiled")

all_results = {}

# ── Step 1: Compile ──
log("=" * 60)
log("  Step 1/3: 编译协议 YAML → IR")
log("=" * 60)

protocols = ["dlt645_2007", "csg_2016"]
ir_map = {}

for proto in protocols:
    ir = compile_protocol(registry, proto, output_dir=compiled_dir)
    ir_map[proto] = ir
    log(f"  ✓ {proto}: {len(ir.frame.fields)} 帧字段, {len(ir.routers)} 路由器, {len(ir.leaves)} 消息/变体")

# ── Step 2: Build → Decode ──
log(f"\n{'=' * 60}")
log(f"  Step 2/3: Build → Decode 往返测试 (resolve_path → build → decode)")
log(f"{'=' * 60}")

for proto in protocols:
    ir = ProtocolIR.from_json_file(f"{compiled_dir}/{proto}.ir.json")
    codecs = create_builtin_registry()
    be = BuildEngine(ir, codecs)
    de = DecodeEngine(ir, create_builtin_registry())

    counters = {"pass": 0, "fail": 0}
    failures = []

    run_protocol_tests(proto, ir, be, de, counters, failures)

    all_results[proto] = {"pass": counters["pass"], "fail": counters["fail"], "failures": failures}
    log(f"  {proto}: {counters['pass']} pass, {counters['fail']} fail")

# ── Step 3: 路由图 ──
log(f"\n{'=' * 60}")
log(f"  Step 3/3: 生成路由图")
log(f"{'=' * 60}")

for proto in protocols:
    svg_path = str(_OUT / f"{proto}_routes.svg")
    generate_svg(ir_map[proto], svg_path)
    size = Path(svg_path).stat().st_size
    log(f"  ✓ {proto} → {svg_path} ({size:,} bytes)")

# ── Summary ──
log(f"\n{'=' * 60}")
log(f"  检查完成 — {ts}")
log(f"{'=' * 60}")

total_pass = sum(r["pass"] for r in all_results.values())
total_fail = sum(r["fail"] for r in all_results.values())

for proto in protocols:
    ir = ir_map[proto]
    r = all_results[proto]
    log(f"  {proto}: {len(ir.frame.fields)}字段, {len(ir.routers)}路由, {len(ir.leaves)}变体, "
        f"测试 {r['pass']}✓/{r['fail']}✗")

log(f"\n  总计: {total_pass} pass, {total_fail} fail")

if total_fail:
    log(f"\n  失败详情:")
    for proto in protocols:
        for f in all_results[proto]["failures"]:
            log(f"    [{proto}] {f}")

rc = 1 if total_fail else 0
log(f"\n  日志: {_log_path}")
log(f"  退出码: {rc}")
_log_file.close()
sys.exit(rc)
