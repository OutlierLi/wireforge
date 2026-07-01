"""/auto_rule 命令处理器。

规则定义 (YAML):
  rules:
    - id: auto_reply_login
      enabled: true
      trigger:
        source: serial:default
        event: frame_received
      condition:
        type: regex
        pattern: "^68.*91.*16$"
      actions:
        - command: /send
          args: { hex: "68 ... 16" }
        - command: /log
          args: { message: "auto reply sent" }
      execution:
        mode: sequential
        cooldown_ms: 500
        on_error: skip
"""

from __future__ import annotations

import re, time, yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from console.response import ok, fail


def has_condition_spec(args: dict) -> bool:
    """add/update 是否提供了有效匹配条件（非 type:any）。"""
    match = args.get("match", args.get("pattern", ""))
    if isinstance(match, str) and match.strip():
        return True
    if isinstance(match, dict) and match:
        return True
    return bool(_collect_decoded_fields(args))


def has_then_action(args: dict) -> bool:
    raw = args.get("then", args.get("actions"))
    if raw is None or raw == "":
        return False
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, list):
        return len(raw) > 0
    return True


def validate_add_args(args: dict) -> dict | None:
    missing: list[dict] = []
    if not str(args.get("id", "")).strip():
        missing.append({
            "key": "id",
            "type": "str",
            "desc": "规则ID（唯一标识）",
            "examples": ["csg_query_vendor_ack", "auto_reply_login"],
            "note": "不可省略，后续管理/测试均依赖 id",
        })
    if not has_condition_spec(args):
        missing.append({
            "key": "match",
            "type": "str",
            "desc": "匹配条件：regex/JSON，或 field/di/afn/dir",
            "examples": ["010300E8", "68.*16"],
            "note": "不可省略，否则规则无匹配意义",
        })
    if not has_then_action(args):
        missing.append({
            "key": "then",
            "type": "str",
            "desc": "匹配后执行的命令",
            "examples": ["/send --hex \"68 ... 16\""],
            "note": "不可省略，否则规则无动作",
        })
    if not missing:
        return None
    return fail("missing required parameter", detail={"missing": missing})

# 全局规则存储
_rules: dict[str, dict] = {}
_rule_history: list[dict] = []
_rx_buffers: dict[str, bytearray] = {}
_last_fired: dict[str, float] = {}


@dataclass
class MatchResult:
    rule_id: str
    rule_name: str
    actions: list[dict]
    timestamp: str = ""


def handle(args: dict[str, Any]) -> dict:
    """分发 /auto_rule 子命令。支持 --sub add 和 /auto_rule add 两种格式。"""
    sub = args.get("sub", "")
    if not sub:
        # 从位置参数中提取
        pos = args.get("_", [])
        if pos:
            sub = pos[0]
    if not sub:
        sub = "list"
    cmd_map = {
        "add":    _add,    "update": _update, "list":   _list,   "show":   _show,
        "enable": _enable, "disable": _disable, "delete": _delete,
        "test":   _test,   "load":   _load,   "history": _history,
    }
    fn = cmd_map.get(sub, _list)
    if sub == "add":
        err = validate_add_args(args)
        if err:
            return err
    return fn(args)


# ── 子命令 ────────────────────────────────────────────────────────────

def _add(args: dict) -> dict:
    rid = str(args.get("id", "")).strip()
    if not rid:
        return fail("missing required parameter", detail={
            "missing": [{"key": "id", "type": "str", "desc": "规则ID"}],
        })
    name = args.get("name", "")
    if rid in _rules:
        return fail(f"rule {rid} already exists")

    rule = {
        "id": rid, "name": name, "enabled": True,
        "proto": _normalize_proto(args.get("proto") or args.get("protocol")),
        "trigger": {"source": args.get("source", "serial:default"),
                     "event": args.get("event", "frame_received")},
        "condition": _parse_condition(args),
        "actions": _parse_actions(args),
        "execution": {
            "mode": args.get("mode", "sequential"),
            "cooldown_ms": int(args.get("cooldown", 0)),
            "on_error": args.get("on_error", "skip"),
        },
    }
    _rules[rid] = rule
    return ok({"added": rid, "rule": rule})


def _list(args: dict) -> dict:
    items = []
    for rid, r in _rules.items():
        items.append({
            "id": rid, "name": r.get("name") or rid,
            "enabled": r.get("enabled", True),
            "actions_count": len(r.get("actions", [])),
        })
    return ok({"rules": items, "count": len(items)})


def _show(args: dict) -> dict:
    rid = args.get("id", "")
    rule = _rules.get(rid)
    if not rule:
        return fail(f"rule {rid} not found")
    return ok({"rule": rule})


def _enable(args: dict) -> dict:
    rid = args.get("id", "")
    if rid not in _rules:
        return fail(f"rule {rid} not found")
    _rules[rid]["enabled"] = True
    return ok({"id": rid, "enabled": True})


def _disable(args: dict) -> dict:
    rid = args.get("id", "")
    if rid not in _rules:
        return fail(f"rule {rid} not found")
    _rules[rid]["enabled"] = False
    return ok({"id": rid, "enabled": False})


def _delete(args: dict) -> dict:
    rid = args.get("id", "")
    if rid not in _rules:
        return fail(f"rule {rid} not found")
    del _rules[rid]
    return ok({"deleted": rid})


def _update(args: dict) -> dict:
    rid = args.get("id", "")
    if rid not in _rules:
        return fail(f"rule {rid} not found")

    rule = _rules[rid]
    if args.get("name"):
        rule["name"] = args["name"]
    if "proto" in args or "protocol" in args:
        rule["proto"] = _normalize_proto(args.get("proto") or args.get("protocol"))
    if any(k in args for k in (
        "match", "pattern", "field", "match_type", "condition_type", "di", "afn", "dir", "func",
    )):
        rule["condition"] = _parse_condition(args)
    if any(k in args for k in ("then", "actions")):
        rule["actions"] = _parse_actions(args)
    if "enabled" in args:
        enabled = args["enabled"]
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")
        rule["enabled"] = bool(enabled)
    if "cooldown" in args:
        rule.setdefault("execution", {})["cooldown_ms"] = int(args["cooldown"])
    if "source" in args:
        rule.setdefault("trigger", {})["source"] = args["source"]
    return ok({"updated": rid, "rule": rule})


def _test(args: dict) -> dict:
    rid = args.get("id", "")
    rule = _rules.get(rid)
    if not rule:
        return fail(f"rule {rid} not found")

    hex_str = args.get("hex", "")
    if not hex_str:
        return fail("hex required for test")

    try:
        frame = bytes.fromhex(hex_str.replace(" ", ""))
    except ValueError:
        return fail("invalid hex")

    match = _match_rule(rule, frame)
    if match:
        return ok({
            "matched": True,
            "rule_id": rid,
            "actions": [{"command": a.get("command"), "args": a.get("args")}
                       for a in match.actions],
        })
    return ok({"matched": False, "rule_id": rid})


def _load(args: dict) -> dict:
    path = args.get("file", args.get("path", ""))
    if not path:
        return fail("file path required")

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return fail(f"failed to load: {e}")

    count = 0
    for rule in data.get("rules", []):
        rid = rule.get("id", "")
        if rid:
            _rules[rid] = rule
            count += 1
    return ok({"loaded": count, "total": len(_rules)})


def _history(args: dict) -> dict:
    rid = args.get("id", "")
    items = [h for h in _rule_history if not rid or h.get("rule_id") == rid]
    return ok({"history": items[-50:], "count": len(items)})


# ── 匹配 ──────────────────────────────────────────────────────────────

def match_all(frame_hex: str, frame_bytes: bytes,
              decoded: dict | None = None,
              *, connection_id: str | None = None,
              event: str = "frame_received") -> list[MatchResult]:
    """对所有启用的规则执行匹配。后添加的规则优先，命中即返回（覆盖较早规则）。"""
    for rid, rule in reversed(list(_rules.items())):
        if not rule.get("enabled", True):
            continue
        if connection_id is not None and not _trigger_matches(rule, connection_id, event):
            continue
        if not _cooldown_ready(rid, rule):
            continue
        cond = rule.get("condition", {})
        if decoded is None and _condition_needs_decode(cond):
            decoded = _decode_request_flat(_rule_proto(rule), frame_bytes)
        match = _match_rule(rule, frame_bytes, decoded)
        if match:
            _mark_fired(rid)
            _rule_history.append({
                "rule_id": rid, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "matched_frame": frame_hex, "match_result": "hit",
                "actions": match.actions,
            })
            return [match]
    return []


def process_rx_chunk(connection_id: str, chunk: bytes) -> None:
    """串口 RX 分帧后触发 frame_received 规则并执行动作（含 /print）。"""
    if not chunk or not _rules:
        return
    from console.handlers.frame_splitter import split_frames

    buf = _rx_buffers.setdefault(connection_id, bytearray())
    buf.extend(chunk)
    frames, remainder = split_frames(bytes(buf))
    for frame in frames:
        _fire_rx_rule(connection_id, frame)
    if remainder and remainder[-1] == 0x16:
        _fire_rx_rule(connection_id, bytes(remainder))
        remainder = b""
    _rx_buffers[connection_id] = bytearray(remainder)


def _fire_rx_rule(connection_id: str, frame: bytes) -> None:
    matches = match_all(
        frame.hex().upper(),
        frame,
        connection_id=connection_id,
        event="frame_received",
    )
    for match in matches:
        execute_actions(match, context={"connection_id": connection_id})


def execute_actions(match: MatchResult, context: dict | None = None) -> list[dict]:
    """执行规则的动作。"""
    import sys
    from console.api import exec_cmd
    results = []
    for action in match.actions:
        cmd = action.get("command", "").lstrip("/")
        args = dict(action.get("args", {}))
        if args is None:
            args = {}
        try:
            r = exec_cmd(cmd, args)
            status = r.get("status", "?")
            output = (r.get("data") or {}).get("output")
            if cmd == "print" and status == "success" and output:
                sys.stdout.write(f"{output}\n")
                sys.stdout.flush()
            results.append({"command": cmd, "status": status,
                           "output": output or r.get("data")})
        except Exception as e:
            results.append({"command": cmd, "status": "error", "error": str(e)})
    return results


def append_action_replies_to_buf(
    rx_buf: bytearray,
    actions: list[dict],
    frame_bytes: bytes,
) -> None:
    """将规则 actions 的回复帧追加到 RX 缓冲（mock://auto 使用）。"""
    for action in actions:
        cmd = str(action.get("command", "")).lstrip("/")
        act_args = action.get("args") or {}
        if cmd in ("send",):
            reply_hex = act_args.get("hex", "")
            if reply_hex:
                try:
                    rx_buf.extend(bytes.fromhex(str(reply_hex).replace(" ", "")))
                except ValueError:
                    pass
        elif cmd == "serial" and act_args.get("sub") == "send":
            reply_hex = act_args.get("hex", "")
            if reply_hex:
                try:
                    rx_buf.extend(bytes.fromhex(str(reply_hex).replace(" ", "")))
                except ValueError:
                    pass
        elif cmd == "build":
            frame_hex = _build_reply_hex(act_args, frame_bytes)
            if frame_hex:
                try:
                    rx_buf.extend(bytes.fromhex(frame_hex.replace(" ", "")))
                except ValueError:
                    pass


# ── helpers ───────────────────────────────────────────────────────────

def _trigger_matches(rule: dict, connection_id: str, event: str) -> bool:
    trigger = rule.get("trigger") or {}
    want_event = str(trigger.get("event") or "frame_received")
    if want_event != event:
        return False
    source = str(trigger.get("source") or "")
    if not source:
        return True
    if source.startswith("serial:"):
        return source.split(":", 1)[1] == connection_id
    return source == connection_id


def _cooldown_ready(rule_id: str, rule: dict) -> bool:
    execution = rule.get("execution") or {}
    cooldown_ms = int(execution.get("cooldown_ms") or 0)
    if cooldown_ms <= 0:
        return True
    last = _last_fired.get(rule_id, 0.0)
    return (time.monotonic() - last) * 1000 >= cooldown_ms


def _mark_fired(rule_id: str) -> None:
    _last_fired[rule_id] = time.monotonic()


_PROTO_ALIASES = {
    "csg": "csg", "csg_2016": "csg",
    "dlt645": "dlt645", "dlt645_2007": "dlt645", "645": "dlt645",
}


def _normalize_proto(raw: Any, default: str = "csg") -> str:
    if raw in (None, ""):
        return default
    key = str(raw).strip().lower()
    return _PROTO_ALIASES.get(key, key)


def _rule_proto(rule: dict) -> str:
    return _normalize_proto(rule.get("proto") or rule.get("protocol"))


_ROUTE_KEYS = ("di", "afn", "dir", "func")
_ROUTE_FIELD_MAP = {
    "di": "user_data.di", "afn": "user_data.afn", "dir": "dir", "func": "func",
}


def _parse_condition(args: dict) -> dict:
    cond_type = args.get("match_type", args.get("condition_type", "regex"))
    pattern = args.get("match", args.get("pattern", ""))

    fields = _collect_decoded_fields(args)
    if fields and not pattern:
        return {"type": "decoded", "fields": fields}

    if isinstance(pattern, dict):
        if "all" in pattern or "any" in pattern:
            return _normalize_composite(pattern)
        if pattern.get("type") == "decoded":
            merged = dict(pattern.get("fields") or {})
            merged.update(_collect_decoded_fields(pattern))
            return {"type": "decoded", "fields": merged}
        route_or_payload = _collect_decoded_fields(pattern)
        extra = {
            k: v for k, v in pattern.items()
            if k not in _ROUTE_KEYS and k not in ("type", "fields", "all", "any")
        }
        for key, value in extra.items():
            route_or_payload[_decoded_field_path(key)] = str(value).strip()
        if route_or_payload:
            return {"type": "decoded", "fields": route_or_payload}
        if "type" in pattern:
            return pattern

    if fields:
        return {"type": "decoded", "fields": fields}

    if isinstance(pattern, list):
        return {"any": [_normalize_leaf_item(item) for item in pattern]}

    if pattern:
        return {"type": cond_type, "pattern": str(pattern)}
    return {"type": "any"}


def _is_decoded_args_context(src: dict) -> bool:
    """仅 decode 路由/字段匹配时收集 payload 级参数（避免吞掉 then 的 text/hex 等）。"""
    match = src.get("match", src.get("pattern"))
    if match is True:
        return True
    if any(src.get(k) not in (None, "") for k in _ROUTE_KEYS):
        return True
    if src.get("field"):
        return True
    if src.get("proto") or src.get("protocol"):
        return True
    return False


def _collect_decoded_fields(src: dict) -> dict[str, str]:
    fields: dict[str, str] = {}
    raw_fields = src.get("field", [])
    if not isinstance(raw_fields, list):
        raw_fields = [raw_fields]
    for f in raw_fields:
        if f and "=" in str(f):
            k, v = str(f).split("=", 1)
            fields[k.strip()] = v.strip()
    for key in _ROUTE_KEYS:
        if key in src and src[key] not in (None, ""):
            fields[_ROUTE_FIELD_MAP[key]] = str(src[key]).strip()
    if _is_decoded_args_context(src):
        for key, val in src.items():
            if key in _ADD_RULE_PARAM_KEYS or key in _ROUTE_KEYS:
                continue
            if val in (None, "", False, True):
                continue
            fields[_decoded_field_path(key)] = str(val).strip()
    return fields


def _decoded_field_path(name: str) -> str:
    if name in ("dir", "add"):
        return name
    if "." in name:
        return name
    return f"user_data.{name}"


def _normalize_composite(cond: dict) -> dict:
    result: dict[str, Any] = {}
    for key in ("all", "any"):
        if key in cond:
            items = cond[key]
            if not isinstance(items, list):
                items = [items]
            result[key] = [_normalize_leaf_item(item) for item in items]
    return result


def _normalize_leaf_item(item: Any) -> dict:
    if isinstance(item, str):
        return {"type": "regex", "pattern": item}
    if isinstance(item, dict):
        if "all" in item or "any" in item:
            return _normalize_composite(item)
        if item.get("type") == "decoded":
            merged = dict(item.get("fields") or {})
            merged.update(_collect_decoded_fields(item))
            extra = {
                k: v for k, v in item.items()
                if k not in _ROUTE_KEYS and k not in ("type", "fields", "all", "any")
            }
            for key, value in extra.items():
                merged[_decoded_field_path(key)] = str(value).strip()
            return {"type": "decoded", "fields": merged}
        if any(k in item for k in _ROUTE_KEYS):
            fields = _collect_decoded_fields(item)
            extra = {
                k: v for k, v in item.items()
                if k not in _ROUTE_KEYS and k not in ("type", "fields", "all", "any")
            }
            for key, value in extra.items():
                fields[_decoded_field_path(key)] = str(value).strip()
            return {"type": "decoded", "fields": fields}
        if "type" not in item and "pattern" in item:
            return {"type": "regex", **item}
        return item
    return {"type": "regex", "pattern": str(item)}


def _parse_actions(args: dict) -> list[dict]:
    actions = []
    raw = args.get("then", args.get("actions", []))
    if isinstance(raw, str):
        raw = _reconstruct_then_value(args)
        raw = [raw]
    elif isinstance(raw, list):
        pass
    else:
        raw = [raw]
    for a in raw:
        if isinstance(a, dict):
            actions.append(a)
        elif isinstance(a, str):
            parsed = _parse_action_string(a)
            if parsed:
                actions.append(parsed)
    return actions


_ADD_RULE_PARAM_KEYS = frozenset({
    "sub", "_", "id", "match", "pattern", "then", "actions", "name", "source", "event",
    "field", "di", "afn", "dir", "func", "proto", "protocol",
    "match_type", "condition_type",
    "cooldown", "mode", "on_error", "enabled",
})


def _reconstruct_then_value(args: dict) -> str:
    """Shell 会把 ``--then /print --text=success`` 拆成 then + text，此处合并回一条命令。"""
    then = str(args.get("then") or "").strip()
    if not then or " " in then:
        return then
    if not then.startswith("/"):
        return then
    suffix: list[str] = []
    for key, val in args.items():
        if key in _ADD_RULE_PARAM_KEYS:
            continue
        if val in (None, "", False):
            continue
        if val is True:
            suffix.append(f"--{key}")
        else:
            suffix.append(f"--{key}={val}")
    if not suffix:
        return then
    return then + " " + " ".join(suffix)


def _parse_action_string(text: str) -> dict | None:
    """解析动作：JSON dict/list、或 ``/cmd --flag=value`` 命令行。"""
    import json

    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("command"):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]

    parts = stripped.split(maxsplit=1)
    cmd = parts[0] if parts else ""
    act_args: dict[str, Any] = {}
    if len(parts) > 1:
        tokens = parts[1].split()
        i = 0
        while i < len(tokens):
            if tokens[i].startswith("--"):
                key = tokens[i][2:]
                if "=" in key:
                    k, v = key.split("=", 1)
                    act_args[k] = v
                    i += 1
                elif key == "hex" and i + 1 < len(tokens):
                    act_args[key] = " ".join(tokens[i + 1:])
                    i = len(tokens)
                elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                    act_args[key] = tokens[i + 1]
                    i += 2
                else:
                    act_args[key] = "true"
                    i += 1
            else:
                i += 1
    return {"command": cmd, "args": act_args}


def _match_rule(rule: dict, frame_bytes: bytes, decoded: dict | None = None) -> MatchResult | None:
    cond = rule.get("condition", {})
    hex_str = frame_bytes.hex().upper()
    if decoded is None and _condition_needs_decode(cond):
        decoded = _decode_request_flat(_rule_proto(rule), frame_bytes)

    if _eval_condition(cond, hex_str, frame_bytes, decoded):
        return MatchResult(
            rule_id=rule["id"],
            rule_name=rule.get("name", ""),
            actions=rule.get("actions", []),
        )
    return None


def _eval_condition(
    cond: dict,
    hex_str: str,
    frame_bytes: bytes,
    decoded: dict | None = None,
) -> bool:
    if "all" in cond:
        items = cond["all"]
        if not isinstance(items, list):
            items = [items]
        return all(_eval_condition(item, hex_str, frame_bytes, decoded) for item in items)

    if "any" in cond:
        items = cond["any"]
        if not isinstance(items, list):
            items = [items]
        return any(_eval_condition(item, hex_str, frame_bytes, decoded) for item in items)

    cond_type = cond.get("type", "regex")

    if cond_type == "regex":
        pattern = cond.get("pattern", "")
        return bool(pattern and re.search(pattern, hex_str))

    if cond_type == "decoded":
        fields = cond.get("fields", {})
        if not decoded:
            return False
        return all(_decoded_value_matches(decoded, k, v) for k, v in fields.items())

    if cond_type == "any":
        return True

    return False


def _normalize_hex_token(value: Any) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value)).upper()


def _parse_int_token(value: Any) -> int | None:
    text = str(value).strip().lower()
    if not text:
        return None
    if text.startswith("0x"):
        try:
            return int(text, 16)
        except ValueError:
            return None
    try:
        return int(text, 10)
    except ValueError:
        return None


def _decoded_value_matches(decoded: dict, field_path: str, expected: Any) -> bool:
    actual = decoded.get(field_path, "")
    if field_path == "user_data.di":
        return _normalize_hex_token(actual) == _normalize_hex_token(expected)
    if field_path in ("user_data.afn", "func", "user_data.func", "control.func"):
        actual_int = _parse_int_token(actual)
        expected_int = _parse_int_token(expected)
        if actual_int is not None and expected_int is not None:
            return actual_int == expected_int
        return str(actual) == str(expected)
    if field_path == "dir":
        return str(actual).lower() == str(expected).lower()
    return str(actual) == str(expected)


def _condition_needs_decode(cond: dict) -> bool:
    if not cond:
        return False
    if cond.get("type") == "decoded":
        return True
    for key in ("all", "any"):
        if key in cond:
            items = cond[key]
            if not isinstance(items, list):
                items = [items]
            return any(_condition_needs_decode(item) for item in items)
    return False


def _build_reply_hex(build_args: dict, frame_bytes: bytes) -> str:
    resolved = _resolve_build_args(build_args, frame_bytes)
    if resolved is None:
        return ""
    from runtime.command_runtime import execute
    result = execute("build", resolved)
    if result.get("status") != "success":
        return ""
    data = result.get("data") or {}
    return str(data.get("frame") or data.get("frame_hex") or "")


def _resolve_build_args(build_args: dict, frame_bytes: bytes) -> dict | None:
    proto = str(build_args.get("proto", "csg"))
    request_flat = _decode_request_flat(proto, frame_bytes)
    if request_flat is None:
        return None

    resolved: dict[str, Any] = {}
    for key, value in build_args.items():
        resolved[key] = _resolve_build_value(value, request_flat, resolved)

    if resolved.get("slave_addrs") == "$generated.slave_addrs":
        start = _coerce_int(
            resolved.get("start_slave_index")
            or request_flat.get("user_data.start_slave_index")
        )
        count = _coerce_int(
            resolved.get("response_slave_count")
            or request_flat.get("user_data.slave_count")
        )
        if start is None or count is None:
            return None
        resolved["slave_addrs"] = generate_slave_addrs(start, count)

    for key in ("response_slave_count", "slave_total", "wait_time"):
        if key in resolved:
            coerced = _coerce_int(resolved[key])
            if coerced is not None:
                resolved[key] = coerced

    # start_slave_index 仅用于生成地址，不应传入 build
    resolved.pop("start_slave_index", None)
    return resolved


def _resolve_build_value(value: Any, request_flat: dict, resolved_so_far: dict) -> Any:
    if isinstance(value, str) and value.startswith("$request."):
        path = value[len("$request."):]
        return request_flat.get(path)
    if isinstance(value, dict):
        return {k: _resolve_build_value(v, request_flat, resolved_so_far) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_build_value(v, request_flat, resolved_so_far) for v in value]
    return value


def _decode_request_flat(proto: str, frame_bytes: bytes) -> dict | None:
    from runtime.command_runtime import execute
    from console.handlers.wait_frame import _flatten_decode_values

    result = execute("decode", {
        "proto": proto,
        "hex": frame_bytes.hex(" ").upper(),
    })
    if result.get("status") != "success":
        return None
    data = result.get("data") or {}
    values = data.get("values") or data.get("decoded") or {}
    if not isinstance(values, dict):
        return None
    return _flatten_decode_values(values, data.get("path", ""))


def generate_slave_addrs(start_slave_index: int, count: int) -> list[str]:
    return [str(start_slave_index + i + 1) for i in range(count)]


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
