"""从 pairing 表生成 TestPlan YAML（mock://auto + 真机共用）。"""

from __future__ import annotations

from typing import Any

import yaml

from tests.csg_pair_catalog import (
    format_pair_di_chain,
    iter_pair_messages,
    load_csg_pairs,
)
from tests.dlt645_pair_catalog import (
    format_pair_chain,
    iter_pair_messages as iter_dlt645_messages,
    load_dlt645_pairs,
)
from tests.protocol_build_utils import (
    build_csg_field_values,
    build_dlt645_field_values,
    run_dlt645_pair_message,
    run_pair_message,
)


def _afn_build_token(afn: str) -> str:
    return f"0x{int(str(afn), 16):02X}"


def _func_build_token(func: str) -> str:
    return f"0x{int(str(func), 16):02X}"


def _match_for_csg_request(msg) -> dict[str, str]:
    return {
        "di": msg.di,
        "afn": msg.afn,
        "dir": msg.dir,
    }


def _match_hex_for_dlt645(frame_hex: str) -> str:
    compact = frame_hex.replace(" ", "").upper()
    if len(compact) <= 48:
        return compact
    return compact[8:-4]


def _expect_from_message(proto_key: str, msg) -> dict[str, str]:
    if proto_key == "csg":
        return {
            "afn": msg.afn,
            "di": msg.di,
            "dir": msg.dir,
        }
    out: dict[str, str] = {"dir": msg.dir}
    if msg.func:
        out["func"] = msg.func
    if msg.di:
        out["di"] = msg.di
    return out


def _resolve_leaf(build_engine, ir, msg, proto_key: str):
    if proto_key == "csg":
        from tests.csg_pair_catalog import to_route_info as route_info
    else:
        from tests.dlt645_pair_catalog import to_route_info as route_info
    path = build_engine.resolve_path(route_info(msg))
    leaf = ir.leaves.get(path["leaf_id"])
    if leaf is None:
        raise RuntimeError(f"leaf not found: {path['leaf_id']}")
    return leaf


def _schema_field_names(route_args: dict[str, Any]) -> set[str]:
    from test_runner.build_schema_check import _resolve_target

    target = _resolve_target(route_args)
    return {f.name for f in target.input_schema}


def _build_message_args(
    proto_key: str,
    msg,
    *,
    build_engine,
    ir,
    defaults: dict[str, Any],
    pair_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """TestPlan build args：路由键 + route input_schema 内字段（来自 pairing 默认值）。"""
    merged = dict(defaults)
    merged.update(pair_defaults or {})
    merged.update(getattr(msg, "field_defaults", {}) or {})

    if proto_key == "csg":
        route: dict[str, Any] = {
            "proto": "csg",
            "afn": _afn_build_token(msg.afn),
            "di": msg.di,
            "dir": msg.dir,
        }
        if msg.has_address:
            route["addr"] = True
        leaf = _resolve_leaf(build_engine, ir, msg, proto_key)
        fv = build_csg_field_values(msg, leaf, merged, ir)
        names = _schema_field_names(route)
        args = dict(route)
        for name in names:
            if name in fv:
                val = fv[name]
                if isinstance(val, bytes):
                    val = val.hex().upper()
                args[name] = val
                continue
            if "." in name:
                parent, child = name.split(".", 1)
                parent_val = fv.get(parent)
                if isinstance(parent_val, dict) and child in parent_val:
                    args[name] = parent_val[child]
        return args

    route = {
        "proto": "dlt645",
        "func": _func_build_token(msg.func),
        "dir": msg.dir,
    }
    if msg.di:
        route["di"] = msg.di
    if msg.freeze_type:
        route["freeze_type"] = msg.freeze_type
    if msg.event_type:
        route["event_type"] = msg.event_type
    for key, val in (getattr(msg, "frame_defaults", {}) or {}).items():
        route[key] = val
    leaf = _resolve_leaf(build_engine, ir, msg, proto_key)
    fv = build_dlt645_field_values(msg, leaf, merged, ir)
    names = _schema_field_names(route)
    args = dict(route)
    for name in names:
        if name not in fv:
            continue
        val = fv[name]
        if isinstance(val, bytes):
            val = val.hex().upper()
        args[name] = val
    return args


def _pair_steps(
    pair: dict[str, Any],
    *,
    proto_key: str,
    ir,
    build_engine,
    decode_engine,
    defaults: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """为单条 pairing 生成 TestPlan steps；无响应则返回 None。"""
    pair_id = pair["id"]
    if proto_key == "csg":
        msg_iter = iter_pair_messages(pair)
        runner = run_pair_message
    else:
        msg_iter = iter_dlt645_messages(pair)
        runner = run_dlt645_pair_message

    messages = list(msg_iter)
    if len(messages) < 2:
        return None

    req = messages[0]
    resps = messages[1:]
    req_result = runner(req, ir, build_engine, decode_engine, defaults)
    if req_result.status != "PASS":
        raise RuntimeError(f"{pair_id} request build failed: {req_result.error}")

    resp_results = []
    for msg in resps:
        r = runner(msg, ir, build_engine, decode_engine, defaults)
        if r.status != "PASS":
            raise RuntimeError(f"{pair_id}/{msg.slot} response build failed: {r.error}")
        resp_results.append(r)

    rule_id = f"rule_{pair_id}"
    pair_defaults = pair.get("field_defaults") or {}

    steps: list[dict[str, Any]] = [
        {
            "id": f"{pair_id}__build_req",
            "action": "build",
            "args": _build_message_args(
                proto_key, req, build_engine=build_engine, ir=ir,
                defaults=defaults, pair_defaults=pair_defaults,
            ),
            "save_as": f"{pair_id}_req",
        },
    ]

    for idx, msg in enumerate(resps):
        steps.append({
            "id": f"{pair_id}__build_resp_{idx}",
            "action": "build",
            "args": _build_message_args(
                proto_key, msg, build_engine=build_engine, ir=ir,
                defaults=defaults, pair_defaults=pair_defaults,
            ),
            "save_as": f"{pair_id}_resp_{idx}",
        })

    then_actions = [
        {
            "command": "/send",
            "args": {"hex": f"${{{pair_id}_resp_{i}.frame_hex}}"},
        }
        for i in range(len(resp_results))
    ]

    if proto_key == "csg":
        match = _match_for_csg_request(req)
    else:
        match = _match_hex_for_dlt645(req_result.frame_hex)

    steps.append({
        "id": f"{pair_id}__mock_setup",
        "action": "if",
        "args": {"when": "port == mock://auto"},
        "steps": [{
            "id": f"{pair_id}__add_rule",
            "action": "auto_rule.add",
            "args": {
                "id": rule_id,
                "source": "serial:${conn}",
                "match": match,
                "then": then_actions,
            },
        }],
    })

    steps.append({
        "id": f"{pair_id}__send",
        "action": "send",
        "args": {
            "conn": "${conn}",
            "hex": f"${{{pair_id}_req.frame_hex}}",
            "timeout": 0,
        },
    })

    for idx, msg in enumerate(resps):
        steps.extend([
            {
                "id": f"{pair_id}__wait_{idx}",
                "action": "wait-frame",
                "args": {
                    "conn": "${conn}",
                    "proto": "${proto}",
                    "timeout_ms": "${wait_timeout_ms}",
                    "expect": _expect_from_message(proto_key, msg),
                },
                "save_as": f"{pair_id}_ack_{idx}",
            },
            {
                "id": f"{pair_id}__assert_{idx}",
                "action": "assert",
                "args": {
                    "expect": {f"{pair_id}_ack_{idx}.matched": True},
                },
            },
        ])

    steps.append({
        "id": f"{pair_id}__mock_teardown",
        "action": "if",
        "args": {"when": "port == mock://auto"},
        "steps": [{
            "id": f"{pair_id}__remove_rule",
            "action": "auto_rule.remove",
            "args": {"id": rule_id},
        }],
    })
    return steps


def build_pair_serial_plan(
    *,
    proto_key: str,
    ir,
    build_engine,
    decode_engine,
    defaults: dict[str, Any],
    pair_id: str | None = None,
) -> dict[str, Any]:
    if proto_key == "csg":
        pairs_data = load_csg_pairs()
        proto_name = "csg_2016"
        plan_name = "csg_pair_serial"
        purpose = "CSG 2016 配对表串口测试：下行 build/send，mock://auto 注入上行响应。"
    else:
        pairs_data = load_dlt645_pairs()
        proto_name = "dlt645_2007"
        plan_name = "dlt645_pair_serial"
        purpose = "DLT645-2007 配对表串口测试：下行 build/send，mock://auto 注入上行响应。"

    steps: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    chains: list[str] = []

    for pair in pairs_data["pairs"]:
        pid = pair["id"]
        if pair_id and pid != pair_id:
            continue
        pair_steps = _pair_steps(
            pair,
            proto_key=proto_key,
            ir=ir,
            build_engine=build_engine,
            decode_engine=decode_engine,
            defaults=defaults,
        )
        if not pair_steps:
            continue
        if proto_key == "csg":
            chains.append(format_pair_di_chain(pair))
        else:
            chains.append(format_pair_chain(pair))
        for ps in pair_steps:
            if ps["action"] == "wait-frame":
                expected.append({
                    "step_id": ps["id"],
                    "description": f"{pid} 收到上行响应",
                    "expect": ps["args"]["expect"],
                })
        steps.extend(pair_steps)

    return {
        "version": 1,
        "name": plan_name if not pair_id else f"{plan_name}_{pair_id}",
        "timeout_ms": 600000,
        "purpose": purpose,
        "expected_results": expected,
        "test_flow": [
            "serial.connect",
            "每条 pairing: build 下行 + build 上行 + mock auto_rule.add（when mock://auto）",
            "send(timeout:0) + wait-frame × N + assert",
            "auto_rule.remove + serial.disconnect",
        ],
        "doc": "database/templates/pair_serial_test_plan.yaml",
        "vars": {
            "port": "mock://auto",
            "conn": "pair_test",
            "baudrate": 9600,
            "proto": "csg" if proto_key == "csg" else "dlt645",
            "wait_timeout_ms": 5000,
        },
        "setup": [
            {
                "id": "connect",
                "action": "serial.connect",
                "args": {
                    "conn": "${conn}",
                    "port": "${port}",
                    "baudrate": "${baudrate}",
                },
            },
        ],
        "steps": steps,
        "teardown": [
            {
                "id": "disconnect",
                "action": "serial.disconnect",
                "args": {"conn": "${conn}"},
            },
        ],
        "_meta": {"pair_chains": chains, "pair_count": len(chains)},
    }


def dump_plan(plan: dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if not k.startswith("_")}
    return yaml.safe_dump(
        body,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
