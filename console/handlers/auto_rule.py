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

# 全局规则存储
_rules: dict[str, dict] = {}
_rule_history: list[dict] = []


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
        "add":    _add,    "list":   _list,   "show":   _show,
        "enable": _enable, "disable": _disable, "delete": _delete,
        "test":   _test,   "load":   _load,   "history": _history,
    }
    fn = cmd_map.get(sub, _list)
    return fn(args)


# ── 子命令 ────────────────────────────────────────────────────────────

def _add(args: dict) -> dict:
    name = args.get("name", "")
    rid = args.get("id", name.replace(" ", "_").lower() or f"rule_{len(_rules)+1}")
    if rid in _rules:
        return fail(f"rule {rid} already exists")

    rule = {
        "id": rid, "name": name, "enabled": True,
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
              decoded: dict | None = None) -> list[MatchResult]:
    """对所有启用的规则执行匹配。后添加优先。"""
    results = []
    for rid, rule in reversed(list(_rules.items())):
        if not rule.get("enabled", True):
            continue
        match = _match_rule(rule, frame_bytes, decoded)
        if match:
            _rule_history.append({
                "rule_id": rid, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "matched_frame": frame_hex, "match_result": "hit",
                "actions": match.actions,
            })
            results.append(match)
    return results


def execute_actions(match: MatchResult, context: dict | None = None) -> list[dict]:
    """执行规则的动作。"""
    from console.api import exec_cmd
    results = []
    for action in match.actions:
        cmd = action.get("command", "").lstrip("/")
        args = dict(action.get("args", {}))
        if args is None:
            args = {}
        try:
            r = exec_cmd(cmd, args)
            results.append({"command": cmd, "status": r.get("status", "?"),
                           "output": r.get("data")})
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

def _parse_condition(args: dict) -> dict:
    cond_type = args.get("match_type", args.get("condition_type", "regex"))
    pattern = args.get("match", args.get("pattern", ""))

    # decoded field matching
    fields = {}
    raw_fields = args.get("field", [])
    if not isinstance(raw_fields, list):
        raw_fields = [raw_fields]
    for f in raw_fields:
        if "=" in str(f):
            k, v = str(f).split("=", 1)
            fields[k.strip()] = v.strip()

    if fields:
        return {"type": "decoded", "fields": fields}

    if isinstance(pattern, dict):
        if "all" in pattern or "any" in pattern:
            return _normalize_composite(pattern)
        if "type" in pattern:
            return pattern

    if isinstance(pattern, list):
        return {"any": [_normalize_leaf_item(item) for item in pattern]}

    if pattern:
        return {"type": cond_type, "pattern": str(pattern)}
    return {"type": "any"}


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
        if "type" not in item and "pattern" in item:
            return {"type": "regex", **item}
        return item
    return {"type": "regex", "pattern": str(item)}


def _parse_actions(args: dict) -> list[dict]:
    actions = []
    raw = args.get("then", args.get("actions", []))
    if isinstance(raw, str):
        raw = [raw]
    for a in raw:
        if isinstance(a, dict):
            actions.append(a)
        elif isinstance(a, str):
            # 解析 "/send --hex ..." 格式
            parts = a.split(maxsplit=1)
            cmd = parts[0] if parts else ""
            act_args = {}
            if len(parts) > 1:
                # 简单解析 --key value
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
                            # --hex 后可能跟带空格的完整帧，取剩余 tokens
                            act_args[key] = " ".join(tokens[i + 1:])
                            i = len(tokens)
                        elif i + 1 < len(tokens) and not tokens[i+1].startswith("--"):
                            act_args[key] = tokens[i+1]
                            i += 2
                        else:
                            act_args[key] = "true"
                            i += 1
                    else:
                        i += 1
            actions.append({"command": cmd, "args": act_args})
    return actions


def _match_rule(rule: dict, frame_bytes: bytes, decoded: dict | None = None) -> MatchResult | None:
    cond = rule.get("condition", {})
    hex_str = frame_bytes.hex().upper()

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
        return all(str(decoded.get(k, "")) == str(v) for k, v in fields.items())

    if cond_type == "any":
        return True

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
