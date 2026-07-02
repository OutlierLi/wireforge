"""`/build` / `/route` 动态补全 — 路由键 → protocol_map 取值 → resolve schema。

路由键顺序（逐层收窄候选）：
  dir → afn/func → di → addr（仅当 AFN+DI 已定时仍存在带/不带地址域的分歧）→ 业务字段

语义：
- AFN / func：类别（初始化、读参数…），标签来自 IR router 描述 + DI 数量
- DI：具体功能（复位硬件、设置时间…），标签来自 protocol_map entry description
- 数据源 protocol_map.yaml + compiled IR，bootstrap/扩展后自动生效
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "compiled" / "protocol_map.yaml"
_IR_PROTO = {"csg": "csg_2016", "dlt645": "dlt645_2007"}

_ROUTE_KEYS: dict[str, tuple[str, ...]] = {
    "csg": ("dir", "afn", "di", "addr"),
    "dlt645": ("dir", "func", "di", "addr"),
}
_ROUTE_META = frozenset({
    "proto", "func", "afn", "di", "dir", "direction", "addr", "has_address",
    "resolve", "schema", "describe", "from_frame", "from-frame", "set", "sub",
    "intent", "preamble", "seq", "freeze_type", "event_type",
})
_MISSING_KEYS_RE = re.compile(r"Provide\s+([\w/]+)\s+to disambiguate", re.I)
_PROTO_NORM = {
    "csg": "csg", "csg_2016": "csg",
    "dlt645": "dlt645", "dlt645_2007": "dlt645", "645": "dlt645",
}


def _proto_family(raw: Any) -> str:
    if raw in (None, ""):
        return ""
    return _PROTO_NORM.get(str(raw).strip().lower(), str(raw).strip().lower())


def _is_protocol_route_mode(used_args: dict[str, Any], *, command: str = "build") -> bool:
    if command == "build" and (used_args.get("from_frame") or used_args.get("from-frame")):
        return False
    return bool(_proto_family(used_args.get("proto")))


def _is_build_dynamic_mode(used_args: dict[str, Any]) -> bool:
    return _is_protocol_route_mode(used_args, command="build")


def _route_key_order(proto: str) -> tuple[str, ...]:
    return _ROUTE_KEYS.get(proto, ())


def _category_route_key(proto: str) -> str:
    return "afn" if proto == "csg" else "func"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _has_address_from_used(used_args: dict[str, Any]) -> bool | None:
    if used_args.get("has_address") not in (None, ""):
        return _coerce_bool(used_args["has_address"])
    if used_args.get("addr") not in (None, ""):
        return _coerce_bool(used_args["addr"])
    return None


def _entry_has_address(entry: dict[str, Any]) -> bool:
    rp = entry.get("route_params") or {}
    return bool(rp.get("has_address"))


def _implicit_has_address_from_entries(entries: list[dict[str, Any]]) -> bool | None:
    values = {_entry_has_address(entry) for entry in entries}
    if len(values) == 1:
        return next(iter(values))
    return None


def _effective_used_args(used_args: dict[str, Any]) -> dict[str, Any]:
    """补全/resolve 用：地址域唯一时隐式注入 has_address。"""
    effective = dict(used_args)
    if _has_address_from_used(effective) is not None:
        effective["has_address"] = _has_address_from_used(effective)
        return effective
    implicit = _implicit_has_address_from_entries(_filter_entries(effective, apply_implicit_addr=False))
    if implicit is not None:
        effective["has_address"] = implicit
    return effective


def _needs_addr_choice(used_args: dict[str, Any]) -> bool:
    """AFN/func + DI + dir 确定后，若仍有多条 has_address 分歧才询问 addr。"""
    if _route_key_used("addr", used_args):
        return False
    proto = _proto_family(used_args.get("proto"))
    if not proto:
        return False
    category = _category_route_key(proto)
    if not _route_key_used("dir", used_args):
        return False
    if not _route_key_used(category, used_args):
        return False
    if not _route_key_used("di", used_args):
        return False
    entries = _filter_entries(used_args, apply_implicit_addr=False)
    values = {_entry_has_address(entry) for entry in entries}
    return len(values) > 1


def _route_key_used(key: str, used_args: dict[str, Any]) -> bool:
    if key == "addr":
        return _has_address_from_used(used_args) is not None
    val = used_args.get(key)
    if val in (None, ""):
        return False
    if val is True:
        return False
    return True


def _parse_missing_route_keys(error: str) -> list[str]:
    m = _MISSING_KEYS_RE.search(error)
    if not m:
        return []
    keys: list[str] = []
    for part in m.group(1).split("/"):
        part = part.strip().lower()
        if part == "add":
            keys.append("addr")
        elif part == "direction":
            keys.append("dir")
        elif part:
            keys.append(part)
    return keys


def _target_info_from_used(used_args: dict[str, Any]) -> dict[str, Any]:
    effective = _effective_used_args(used_args)
    info: dict[str, Any] = {}
    proto = _proto_family(effective.get("proto"))
    if proto:
        info["proto"] = proto
    for key in ("func", "afn", "di", "dir", "direction", "freeze_type", "event_type"):
        if effective.get(key) not in (None, ""):
            info[key] = effective[key]
    has_address = _has_address_from_used(effective)
    if has_address is not None:
        info["has_address"] = has_address
    elif effective.get("has_address") not in (None, ""):
        info["has_address"] = effective["has_address"]
    if effective.get("addr") not in (None, ""):
        info["addr"] = effective["addr"]
    return info


@lru_cache(maxsize=1)
def _load_protocol_map() -> dict[str, Any]:
    if not MAP_PATH.exists():
        return {"protocols": {}}
    with open(MAP_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {"protocols": {}}


def _iter_entries(proto: str) -> list[dict[str, Any]]:
    data = _load_protocol_map()
    out: list[dict[str, Any]] = []
    for pinfo in (data.get("protocols") or {}).values():
        for entry in pinfo.get("entries") or []:
            rp = entry.get("route_params") or {}
            if _proto_family(rp.get("proto")) == proto:
                out.append(entry)
    return out


def _normalize_hex(value: Any) -> str:
    text = str(value).strip().replace(" ", "")
    if text.lower().startswith("0x"):
        text = text[2:]
    return text.upper()


def _filter_entries(
    used_args: dict[str, Any],
    *,
    apply_implicit_addr: bool = True,
) -> list[dict[str, Any]]:
    proto = _proto_family(used_args.get("proto"))
    if not proto:
        return []
    entries = _iter_entries(proto)
    has_address = _has_address_from_used(used_args)
    if has_address is None and apply_implicit_addr:
        has_address = _implicit_has_address_from_entries(
            _filter_entries(used_args, apply_implicit_addr=False),
        )
    result: list[dict[str, Any]] = []
    for entry in entries:
        rp = entry.get("route_params") or {}
        if used_args.get("afn") not in (None, ""):
            if _normalize_hex(rp.get("afn")) != _normalize_hex(used_args["afn"]):
                continue
        if used_args.get("func") not in (None, ""):
            if _normalize_hex(rp.get("func")) != _normalize_hex(used_args["func"]):
                continue
        if used_args.get("di") not in (None, ""):
            if _normalize_hex(rp.get("di")) != _normalize_hex(str(used_args["di"]).replace(" ", "")):
                continue
        if used_args.get("dir") not in (None, ""):
            if str(rp.get("dir", "")).lower() != str(used_args["dir"]).lower():
                continue
        if has_address is not None and _entry_has_address(entry) != has_address:
            continue
        result.append(entry)
    return result


def _distinct_values(entries: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        rp = entry.get("route_params") or {}
        val = rp.get(key)
        if val in (None, ""):
            continue
        if key in ("afn", "func"):
            text = f"0x{_normalize_hex(val)}"
        elif key == "di":
            text = _normalize_hex(val)
        else:
            text = str(val)
        if text not in seen:
            seen.add(text)
            out.append(text)
    out.sort()
    return out


def _distinct_di_values(entries: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """DI 取值：每条 entry 的 description 即具体功能名。"""
    by_di: dict[str, str] = {}
    for entry in entries:
        rp = entry.get("route_params") or {}
        di = _normalize_hex(rp.get("di"))
        if not di:
            continue
        desc = str(entry.get("description") or entry.get("name") or "").strip()
        if di not in by_di or (desc and not by_di[di]):
            by_di[di] = desc
    return sorted(by_di.items())


@lru_cache(maxsize=4)
def _load_ir_routers(proto_family: str) -> dict[str, Any]:
    ir_name = _IR_PROTO.get(proto_family, proto_family)
    path = ROOT / "compiled" / f"{ir_name}.ir.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("routers") or {}


def _parse_router_category(router_desc: str) -> str:
    """从 router description 提取类别名，如 ``AFN=01 初始化 — ...`` → ``初始化``。"""
    text = str(router_desc or "").strip()
    if not text:
        return ""
    head = re.split(r"[—\-–]", text, maxsplit=1)[0].strip()
    if "=" in head:
        head = head.split("=", 1)[1].strip()
    if " " in head:
        head = head.split(" ", 1)[1].strip()
    return head


def _category_label_for_afn(proto_family: str, afn_norm: str, di_count: int) -> str:
    routers = _load_ir_routers(proto_family)
    afn_int = int(afn_norm, 16)
    router_id = f"afn{afn_int:02d}_di_router"
    category = _parse_router_category(str((routers.get(router_id) or {}).get("description") or ""))
    if category:
        return f"{category} ({di_count} DI)"
    return f"{di_count} DI"


def _category_label_for_func(_proto_family: str, _func_norm: str, di_count: int) -> str:
    return f"{di_count} DI"


def _distinct_category_values(
    entries: list[dict[str, Any]],
    key: str,
    proto_family: str,
) -> list[tuple[str, str]]:
    """AFN/func 取值：按类别聚合，不用 leaf 级 description。"""
    groups: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        rp = entry.get("route_params") or {}
        raw = rp.get(key)
        if raw in (None, ""):
            continue
        if key in ("afn", "func"):
            text = f"0x{_normalize_hex(raw)}"
        else:
            text = str(raw)
        di = _normalize_hex(rp.get("di"))
        if di:
            groups[text].add(di)
        else:
            groups[text].add(text)

    out: list[tuple[str, str]] = []
    for text in sorted(groups.keys()):
        di_count = len(groups[text])
        norm = _normalize_hex(text.replace("0x", ""))
        if key == "afn":
            desc = _category_label_for_afn(proto_family, norm, di_count)
        elif key == "func":
            desc = _category_label_for_func(proto_family, norm, di_count)
        else:
            desc = f"{di_count} DI"
        out.append((text, desc))
    return out


def _distinct_values_labeled(
    entries: list[dict[str, Any]],
    key: str,
    *,
    proto_family: str = "",
) -> list[tuple[str, str]]:
    if key == "di":
        return _distinct_di_values(entries)
    if key in ("afn", "func"):
        return _distinct_category_values(entries, key, proto_family)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for entry in entries:
        rp = entry.get("route_params") or {}
        val = rp.get(key)
        if val in (None, ""):
            continue
        text = str(val)
        if text in seen:
            continue
        seen.add(text)
        out.append((text, ""))
    out.sort(key=lambda x: x[0])
    return out


def _entries_for_route_value(used_args: dict[str, Any], param_key: str) -> list[dict[str, Any]]:
    if param_key == "addr":
        return _filter_entries(used_args, apply_implicit_addr=False)
    if param_key == "dir":
        partial = {k: v for k, v in used_args.items() if k != "dir"}
        return _filter_entries(partial, apply_implicit_addr=False)
    if param_key in ("afn", "func", "di"):
        return _filter_entries(used_args, apply_implicit_addr=False)
    return _filter_entries(used_args, apply_implicit_addr=True)


def _distinct_addr_values(entries: list[dict[str, Any]]) -> list[tuple[str, str]]:
    values = {_entry_has_address(entry) for entry in entries}
    out: list[tuple[str, str]] = []
    if False in values:
        out.append(("false", "无地址域"))
    if True in values:
        out.append(("true", "带地址域"))
    return out


def _collect_pending_route_keys(used_args: dict[str, Any]) -> list[str]:
    proto = _proto_family(used_args.get("proto"))
    order = list(_route_key_order(proto))
    pending: list[str] = []
    for key in order:
        if key == "addr" and not _needs_addr_choice(used_args):
            continue
        if not _route_key_used(key, used_args):
            pending.append(key)
    if pending:
        return pending
    err = _try_resolve_error(used_args)
    if err:
        missing = _parse_missing_route_keys(err)
        if missing:
            return [k for k in missing if not _route_key_used(k, used_args)]
    return []


def _value_prefix_matches(candidate: str, prefix: str) -> bool:
    if not prefix:
        return True
    return candidate.lower().startswith(prefix.lower())


def _flag_matches(flag: str, prefix: str) -> bool:
    if not prefix:
        return True
    if prefix.startswith("--"):
        return flag.startswith(prefix) or flag[2:].startswith(prefix[2:])
    return flag[2:].startswith(prefix.lstrip("-"))


def _make_flag_item(key: str, *, required: bool = False, desc: str = "", dynamic: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "argument",
        "value": f"--{key}",
        "label": f"--{key}",
        "type": "str",
        "required": required,
    }
    if desc:
        item["description"] = desc
    if dynamic:
        item["dynamic"] = True
    return item


def _make_value_item(
    val: str,
    param: str,
    *,
    default: bool = False,
    description: str = "",
) -> dict[str, Any]:
    label = f"{val} (default)" if default else val
    if description and not default:
        label = f"{val} — {description}"
    item: dict[str, Any] = {
        "kind": "argument_value",
        "value": val,
        "label": label,
        "param": param,
    }
    if default:
        item["default"] = True
    if description:
        item["description"] = description
    return item


@lru_cache(maxsize=128)
def _resolve_schema_cached(
    frozen_used: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, bool, str, str], ...] | None:
    used = dict(frozen_used)
    from console.build_resolver import resolve

    try:
        target = resolve(_target_info_from_used(used))
    except Exception:
        return None
    fields: list[tuple[str, bool, str, str]] = []
    for field in target.input_schema:
        if field.name in _ROUTE_META:
            continue
        if field.derived:
            continue
        default_text = "" if field.default is None else str(field.default)
        fields.append((field.name, bool(field.required), field.desc or "", default_text))
    return tuple(fields)


def _schema_fields(used_args: dict[str, Any]) -> list[tuple[str, bool, str, str]]:
    effective = _effective_used_args(used_args)
    frozen = tuple(sorted((k, str(v)) for k, v in effective.items() if v not in (None, "")))
    cached = _resolve_schema_cached(frozen)
    return list(cached or [])


def _try_resolve_error(used_args: dict[str, Any]) -> str | None:
    from console.build_resolver import resolve

    try:
        resolve(_target_info_from_used(used_args))
        return None
    except Exception as exc:
        return str(exc)


def _next_route_keys(used_args: dict[str, Any]) -> list[str]:
    return _collect_pending_route_keys(used_args)


def _field_used(name: str, used_args: dict[str, Any]) -> bool:
    if name in used_args and used_args[name] not in (None, ""):
        return True
    prefix = f"{name}."
    for key in used_args:
        if key.startswith(prefix) and used_args[key] not in (None, ""):
            return True
    return False


def schema_field_meta(used_args: dict[str, Any], key: str) -> dict[str, Any] | None:
    if _is_from_frame_mode(used_args):
        for name, required, desc, ftype, _current in _from_frame_schema_rows(used_args):
            if name == key:
                return {"type": "str", "required": required, "desc": desc or ftype}
    for name, required, desc, default in _schema_fields(used_args):
        if name == key:
            meta: dict[str, Any] = {"type": "str", "required": required, "desc": desc}
            if default:
                meta["default"] = default
            return meta
    return None


def protocol_route_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
    *,
    command: str = "build",
) -> list[dict[str, Any]] | None:
    if not _is_protocol_route_mode(used_args, command=command):
        return None

    completions: list[dict[str, Any]] = []
    typing_flag = bool(flag_prefix)

    route_keys = _next_route_keys(used_args)
    for key in route_keys:
        flag = f"--{key}"
        if typing_flag and not _flag_matches(flag, flag_prefix):
            continue
        desc = {
            "dir": "传输方向（downlink/uplink）",
            "addr": "地址域（false=无地址域，true=带地址域）",
            "afn": "应用功能码 AFN（类别：初始化/读参数/…，具体功能看 DI）",
            "func": "功能码 func（类别，具体功能看 DI）",
            "di": "数据标识 DI（决定具体功能）",
        }.get(key, "")
        completions.append(_make_flag_item(key, desc=desc, dynamic=True))
        if not typing_flag:
            return completions

    if typing_flag and completions:
        return completions

    if command in ("build", "serial_send_build"):
        schema = _schema_fields(used_args)
        if schema:
            for name, required, desc, _default in schema:
                if _field_used(name, used_args):
                    continue
                flag = f"--{name}"
                if typing_flag and not _flag_matches(flag, flag_prefix):
                    continue
                completions.append(_make_flag_item(name, required=required, desc=desc, dynamic=True))
                if not typing_flag:
                    break
            if completions:
                return completions

    return completions if completions else []


# ── from-frame: decode → 可替换字段联想 ─────────────────────────────

def _is_from_frame_mode(used_args: dict[str, Any]) -> bool:
    return bool(used_args.get("from_frame") or used_args.get("from-frame"))


def _compact_hex(text: str) -> str:
    return text.replace(" ", "").replace("\n", "").replace("\t", "").upper()


def _extract_from_frame_hex(used_args: dict[str, Any]) -> str:
    chunks: list[str] = []
    raw = used_args.get("from_frame", used_args.get("from-frame"))
    if raw not in (None, "", True, False):
        if isinstance(raw, list):
            chunks.extend(str(x) for x in raw)
        else:
            chunks.append(str(raw))
    for token in used_args.get("_") or []:
        chunks.append(str(token))
    return " ".join(chunks).strip()


def _looks_like_complete_frame_hex(hex_text: str) -> bool:
    compact = _compact_hex(hex_text)
    if len(compact) < 4 or len(compact) % 2:
        return False
    try:
        bytes.fromhex(compact)
    except ValueError:
        return False
    return True


def _format_cli_field_value(value: Any) -> str:
    if isinstance(value, list):
        inner = ", ".join(_format_cli_field_value(item) for item in value)
        return f"[{inner}]"
    if isinstance(value, dict):
        return str(value.get("raw", value))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _format_set_assignment(name: str, value: Any) -> str:
    return f"{name}={_format_cli_field_value(value)}"


def _pick_decoded_value(field_name: str, flat: dict[str, Any]) -> Any:
    if field_name in flat:
        return flat[field_name]
    matches = [(key, val) for key, val in flat.items() if key == field_name or key.endswith(f".{field_name}")]
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0].count("."), len(item[0])))
    return matches[0][1]


def _parse_set_overrides(used_args: dict[str, Any]) -> dict[str, Any]:
    from console.handlers.build import _parse_set_args

    return _parse_set_args(used_args.get("set"))


def _from_frame_fields_used(used_args: dict[str, Any]) -> set[str]:
    used = set(_parse_set_overrides(used_args))
    for key, val in used_args.items():
        if key in _ROUTE_META or val in (None, "", True):
            continue
        if key.startswith("_"):
            continue
        used.add(key)
    return used


@lru_cache(maxsize=64)
def _from_frame_schema_cached(
    compact_hex: str,
    proto_hint: str,
) -> tuple[tuple[str, bool, str, str, str], ...] | None:
    if not _looks_like_complete_frame_hex(compact_hex):
        return None
    from console.build_resolver import decode_frame, resolve
    from console.handlers.build import _flatten_values

    proto = proto_hint.strip() if proto_hint else ""
    try:
        decoded = decode_frame(compact_hex, proto=proto or None)
    except Exception:
        return None

    target_info = dict(decoded["target_info"])
    if proto:
        target_info["proto"] = proto
    try:
        target = resolve(target_info)
    except Exception:
        return None

    flat = _flatten_values(decoded["values"])
    rows: list[tuple[str, bool, str, str, str]] = []
    for field in target.input_schema:
        if field.name in _ROUTE_META or field.derived:
            continue
        current = _pick_decoded_value(field.name, flat)
        if current is None:
            continue
        rows.append((
            field.name,
            bool(field.required),
            field.desc or "",
            field.type,
            _format_cli_field_value(current),
        ))
    return tuple(rows) if rows else None


def _from_frame_schema_rows(used_args: dict[str, Any]) -> list[tuple[str, bool, str, str, str]]:
    hex_text = _extract_from_frame_hex(used_args)
    if not hex_text:
        return []
    proto = str(used_args.get("proto") or "")
    cached = _from_frame_schema_cached(_compact_hex(hex_text), proto)
    return list(cached or [])


def from_frame_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]] | None:
    if not _is_from_frame_mode(used_args):
        return None

    rows = _from_frame_schema_rows(used_args)
    if not rows:
        return None

    used_fields = _from_frame_fields_used(used_args)
    typing_flag = bool(flag_prefix)
    completions: list[dict[str, Any]] = []
    pending = [
        (name, required, desc, ftype, current)
        for name, required, desc, ftype, current in rows
        if name not in used_fields
    ]

    def _append_set_suggestion(name: str, required: bool, desc: str, current: str) -> None:
        assignment = _format_set_assignment(name, current)
        completions.append({
            "kind": "argument",
            "value": f"--set {assignment}",
            "label": f"--set {assignment}",
            "type": "str",
            "required": False,
            "description": desc or f"当前 {current}",
            "dynamic": True,
            "recommended": True,
        })
        completions.append({
            "kind": "argument",
            "value": f"--{name}={current}",
            "label": f"--{name}={current}",
            "type": "str",
            "required": False,
            "description": desc or f"直接覆盖 {name}",
            "dynamic": True,
        })

    if typing_flag:
        if _flag_matches("--resolve", flag_prefix):
            completions.append(_make_flag_item("resolve", desc="查看 input_schema 与解码值", dynamic=True))
        if _flag_matches("--set", flag_prefix):
            completions.append(_make_flag_item("set", desc="覆盖解码字段（field=value）", dynamic=True))
        if _flag_matches("--proto", flag_prefix) and used_args.get("proto") in (None, "", True):
            completions.append(_make_flag_item("proto", desc="协议类型（省略则自动检测）", dynamic=True))

        set_tail = flag_prefix.lstrip("-")
        if set_tail.startswith("set"):
            set_tail = set_tail[3:].lstrip(" =")

        for name, required, desc, _ftype, current in pending:
            assignment = _format_set_assignment(name, current)
            direct_flag = f"--{name}"
            if set_tail and not (
                name.startswith(set_tail)
                or assignment.startswith(set_tail)
            ):
                continue
            if _flag_matches(direct_flag, flag_prefix):
                completions.append(_make_flag_item(name, required=required, desc=desc, dynamic=True))
                continue
            if _flag_matches("--set", flag_prefix) or set_tail:
                _append_set_suggestion(name, required, desc, current)
        return completions if completions else []

    if pending:
        name, required, desc, _ftype, current = pending[0]
        _append_set_suggestion(name, required, desc, current)
        return completions

    completions.append(_make_flag_item("resolve", desc="查看 input_schema 与解码值", dynamic=True))
    if used_args.get("proto") in (None, "", True):
        completions.append(_make_flag_item("proto", desc="协议类型（省略则自动检测）", dynamic=True))
    return completions


def from_frame_argument_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]] | None:
    if not _is_from_frame_mode(used_args):
        return None

    rows = _from_frame_schema_rows(used_args)
    if not rows:
        return None

    by_name = {name: (required, desc, ftype, current) for name, required, desc, ftype, current in rows}

    if param_key == "set":
        out: list[dict[str, Any]] = []
        prefix = value_prefix.strip()
        if "=" in prefix:
            field_part, val_part = prefix.split("=", 1)
            field_part = field_part.strip()
            for name, (_req, desc, _ftype, current) in by_name.items():
                if field_part and not name.startswith(field_part):
                    continue
                if val_part == "" or str(current).lower().startswith(val_part.lower()):
                    out.append(_make_value_item(
                        str(current),
                        "set",
                        description=desc or name,
                    ))
            return out

        for name, (_req, desc, _ftype, current) in by_name.items():
            assignment = _format_set_assignment(name, current)
            if prefix and not (name.startswith(prefix) or assignment.startswith(prefix)):
                continue
            out.append(_make_value_item(
                assignment,
                "set",
                description=desc or f"当前 {current}",
            ))
        return out

    matched = by_name.get(param_key)
    if matched is None:
        return None
    _req, desc, _ftype, current = matched
    return [
        _make_value_item(
            current,
            param_key,
            default=(not value_prefix),
            description=desc or f"解码值 {current}",
        )
        for current in [current]
        if _value_prefix_matches(current, value_prefix)
    ]


def build_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]] | None:
    dynamic = from_frame_argument_completions(used_args, flag_prefix)
    if dynamic is not None:
        return dynamic
    return protocol_route_argument_completions(used_args, flag_prefix, command="build")


def route_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]] | None:
    return protocol_route_argument_completions(used_args, flag_prefix, command="route")


def protocol_route_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
    *,
    command: str = "build",
) -> list[dict[str, Any]] | None:
    if not _is_protocol_route_mode(used_args, command=command):
        return None

    if param_key in ("afn", "func", "di", "dir", "addr"):
        entries = _entries_for_route_value(used_args, param_key)
        proto = _proto_family(used_args.get("proto"))
        if param_key == "addr":
            labeled = _distinct_addr_values(entries)
        else:
            labeled = _distinct_values_labeled(entries, param_key, proto_family=proto)

        out = [
            _make_value_item(val, param_key, description=desc)
            for val, desc in labeled
            if _value_prefix_matches(val, value_prefix)
        ]
        if param_key in ("dir", "addr") and not value_prefix and out:
            if len(out) == 1:
                out[0]["default"] = True
                out[0]["label"] = f"{out[0]['value']} (default)"
            elif param_key == "dir" and any(c["value"] == "downlink" for c in out):
                for item in out:
                    if item["value"] == "downlink":
                        item["default"] = True
                        item["label"] = "downlink (default)"
                        break
            elif param_key == "addr" and any(c["value"] == "false" for c in out):
                for item in out:
                    if item["value"] == "false":
                        item["default"] = True
                        item["label"] = "false (default)"
                        break
        return out

    if command not in ("build", "serial_send_build", "route"):
        return None

    schema = _schema_fields(used_args)
    for name, _required, _desc, default in schema:
        if name != param_key:
            continue
        vals: list[str] = []
        if default:
            vals.append(default)
        return [
            _make_value_item(v, param_key, default=(i == 0 and not value_prefix))
            for i, v in enumerate(vals)
            if _value_prefix_matches(v, value_prefix)
        ]

    return None


def build_argument_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]] | None:
    dynamic = from_frame_argument_value_completions(used_args, param_key, value_prefix)
    if dynamic is not None:
        return dynamic
    return protocol_route_value_completions(
        used_args, param_key, value_prefix, command="build",
    )


def route_argument_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]] | None:
    return protocol_route_value_completions(
        used_args, param_key, value_prefix, command="route",
    )


_AUTO_RULE_MATCH_ENTRY_FLAGS: tuple[tuple[str, str], ...] = (
    ("proto", "协议 decode 匹配（按 AFN/DI/字段，同 /build 路由）"),
    ("field", "解码字段 path=value（可多次）"),
)

_AUTO_RULE_MATCH_REGEX_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("68.*16", "正则：完整帧"),
    ("010300E8", "正则：DI hex 片段"),
)


def _auto_rule_match_entry_completions(flag_prefix: str) -> list[dict[str, Any]]:
    """``--match `` 后尚未选协议时：正则示例或进入 decode 路由。"""
    typing_flag = bool(flag_prefix)
    items: list[dict[str, Any]] = []
    for key, desc in _AUTO_RULE_MATCH_ENTRY_FLAGS:
        flag = f"--{key}"
        if typing_flag and not _flag_matches(flag, flag_prefix):
            continue
        items.append(_make_flag_item(key, desc=desc))
    if typing_flag:
        return items
    for val, desc in _AUTO_RULE_MATCH_REGEX_EXAMPLES:
        items.append({
            "kind": "argument_value",
            "value": val,
            "label": f"{val} — {desc}",
            "param": "match",
            "description": desc,
        })
    return items


def auto_rule_match_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]] | None:
    if not _proto_family(used_args.get("proto")):
        return _auto_rule_match_entry_completions(flag_prefix)
    return _auto_rule_match_route_argument_completions(used_args, flag_prefix)


_AUTO_RULE_MATCH_ROUTE_DESC = {
    "dir": "按方向匹配（可选）",
    "addr": "按地址域匹配（可选）",
    "afn": "按 AFN 匹配（类别，可选）",
    "func": "按 func 匹配（DLT645，可选）",
    "di": "按 DI 匹配（具体功能，可选）",
}


def _auto_rule_match_route_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]]:
    """auto_rule decode 匹配：仅路由键 + field，不要求完整 build schema。"""
    proto = _proto_family(used_args.get("proto"))
    if not proto:
        return []
    typing_flag = bool(flag_prefix)
    completions: list[dict[str, Any]] = []
    for key in _collect_pending_route_keys(used_args):
        flag = f"--{key}"
        if typing_flag and not _flag_matches(flag, flag_prefix):
            continue
        completions.append(_make_flag_item(
            key,
            desc=_AUTO_RULE_MATCH_ROUTE_DESC.get(key, ""),
            dynamic=True,
        ))
    field_flag = "--field"
    if not typing_flag or _flag_matches(field_flag, flag_prefix):
        completions.append(_make_flag_item(
            "field", desc="解码字段 path=value（可多次，可选）",
        ))
    return completions


def auto_rule_match_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]] | None:
    if param_key in ("proto", "protocol") and not _proto_family(used_args.get("proto")):
        out: list[dict[str, Any]] = []
        for val, default in (("csg", True), ("dlt645", False)):
            if _value_prefix_matches(val, value_prefix):
                out.append(_make_value_item(val, "proto", default=default and not value_prefix))
        return out
    return protocol_route_value_completions(
        used_args, param_key, value_prefix, command="auto_rule_match",
    )


def serial_send_build_argument_completions(
    used_args: dict[str, Any],
    flag_prefix: str,
) -> list[dict[str, Any]] | None:
    if not _proto_family(used_args.get("proto")):
        typing_flag = bool(flag_prefix)
        items: list[dict[str, Any]] = []
        flag = "--proto"
        if not typing_flag or _flag_matches(flag, flag_prefix):
            items.append(_make_flag_item(
                "proto", required=True,
                desc="协议类型（CSG/DLT645，同 /build）",
            ))
        return items
    return protocol_route_argument_completions(
        used_args, flag_prefix, command="serial_send_build",
    )


def serial_send_build_value_completions(
    used_args: dict[str, Any],
    param_key: str,
    value_prefix: str,
) -> list[dict[str, Any]] | None:
    if param_key in ("proto", "protocol") and not _proto_family(used_args.get("proto")):
        out: list[dict[str, Any]] = []
        for val, default in (("csg", True), ("dlt645", False)):
            if _value_prefix_matches(val, value_prefix):
                out.append(_make_value_item(val, "proto", default=default and not value_prefix))
        return out
    return protocol_route_value_completions(
        used_args, param_key, value_prefix, command="serial_send_build",
    )
