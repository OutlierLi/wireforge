"""Deterministic protocol map generated from compiled protocol IR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPILED_DIR = ROOT / "compiled"
PROTOCOL_MAP_PATH = COMPILED_DIR / "protocol_map.json"
BOOTSTRAP_COMMAND = "python3 scripts/bootstrap_protocol_cache.py"


class ProtocolMapMissingError(FileNotFoundError):
    """Raised when the prebuilt protocol-map cache is missing."""


def load_protocol_map(compiled_dir: str | Path | None = None) -> dict[str, Any]:
    """Load the prebuilt protocol-map cache used by the MCP runtime."""

    base = Path(compiled_dir) if compiled_dir else COMPILED_DIR
    path = base / "protocol_map.json"
    if not path.exists():
        raise ProtocolMapMissingError(
            f"protocol map cache missing: {path}. Run `{BOOTSTRAP_COMMAND}` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_protocol_map_from_ir(compiled_dir: str | Path | None = None) -> dict[str, Any]:
    """Scan compiled ``*.ir.json`` files and return a deterministic route map."""

    base = Path(compiled_dir) if compiled_dir else COMPILED_DIR
    protocols: dict[str, Any] = {}
    for ir_file in sorted(base.glob("*.ir.json")):
        if ir_file.name == "protocol_map.json":
            continue
        ir = json.loads(ir_file.read_text(encoding="utf-8"))
        proto = str(ir.get("protocol") or ir_file.stem.replace(".ir", ""))
        entries = _collect_entries(ir, proto)
        if entries:
            protocols[proto] = {
                "name": ir.get("name") or proto,
                "entries": entries,
            }
    return {"version": 1, "protocols": protocols}


def compact_protocol_map(protocol_map: dict[str, Any]) -> dict[str, Any]:
    """Return the Agent-facing map with only matching-critical fields."""

    protocols: dict[str, Any] = {}
    for proto, info in (protocol_map.get("protocols") or {}).items():
        protocols[proto] = {
            "name": info.get("name") or proto,
            "entries": [
                {
                    "id": entry["id"],
                    "entry_id": entry["entry_id"],
                    "leaf_id": entry["leaf_id"],
                    "name": entry["name"],
                    "description": entry["description"],
                    "route_params": entry["route_params"],
                    "path": entry["path"],
                    "route_nodes": entry["route_nodes"],
                    "fields": entry["fields"],
                }
                for entry in info.get("entries") or []
            ],
        }
    return {"version": protocol_map.get("version", 1), "protocols": protocols}


def protocol_map_to_yaml(protocol_map: dict[str, Any]) -> str:
    """Serialize compact protocol map to the bootstrap YAML format."""
    lines = [f"version: {protocol_map.get('version', 1)}", "", "protocols:"]
    for proto, info in (protocol_map.get("protocols") or {}).items():
        lines.append(f"  {proto}:")
        lines.append(f'    name: "{info.get("name", proto)}"')
        lines.append("    entries:")
        for entry in info.get("entries") or []:
            path = ", ".join(entry.get("path") or [])
            fields = ", ".join(entry.get("fields") or [])
            route_params = json.dumps(entry.get("route_params") or {}, ensure_ascii=False, sort_keys=True)
            lines.append(f"      - id: {entry.get('id')}")
            lines.append(f"        entry_id: {entry.get('entry_id')}")
            lines.append(f"        leaf_id: {entry.get('leaf_id')}")
            lines.append(f'        name: "{entry.get("name", "")}"')
            lines.append(f'        description: "{entry.get("description", "")}"')
            lines.append(f"        path: [{path}]")
            lines.append(f"        route_params: {route_params}")
            if fields:
                lines.append(f"        fields: [{fields}]")
    return "\n".join(lines) + "\n"


def write_protocol_map_cache(
    protocol_map: dict[str, Any],
    compiled_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write ``protocol_map.json`` and ``protocol_map.yaml`` under compiled dir."""
    base = Path(compiled_dir) if compiled_dir else COMPILED_DIR
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / "protocol_map.json"
    yaml_path = base / "protocol_map.yaml"
    json_path.write_text(
        json.dumps(protocol_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    yaml_path.write_text(protocol_map_to_yaml(protocol_map), encoding="utf-8")
    return json_path, yaml_path


def refresh_protocol_map_cache(compiled_dir: str | Path | None = None) -> dict[str, Any]:
    """Rebuild map from compiled IR and persist json+yaml caches."""
    base = Path(compiled_dir) if compiled_dir else COMPILED_DIR
    protocol_map = compact_protocol_map(build_protocol_map_from_ir(base))
    write_protocol_map_cache(protocol_map, base)
    return protocol_map


def find_entry(protocol_map: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    leaf_matches: list[dict[str, Any]] = []
    for proto in (protocol_map.get("protocols") or {}).values():
        for entry in proto.get("entries") or []:
            if entry.get("entry_id") == entry_id or entry.get("id") == entry_id:
                return dict(entry)
            if entry.get("leaf_id") == entry_id:
                leaf_matches.append(entry)
    if len(leaf_matches) == 1:
        return dict(leaf_matches[0])
    if len(leaf_matches) > 1:
        choices = ", ".join(str(entry.get("entry_id") or entry.get("id")) for entry in leaf_matches)
        raise ValueError(f"ambiguous protocol map entry: {entry_id}. Use full entry_id or route_params. choices: {choices}")
    return None


def _collect_entries(ir: dict[str, Any], proto: str) -> list[dict[str, Any]]:
    frame_router = _frame_router_id(ir)
    if not frame_router:
        return []

    entries: list[dict[str, Any]] = []
    routers = ir.get("routers") or {}
    for route_key, target_id in sorted((routers.get(frame_router, {}).get("route_table") or {}).items()):
        _walk(
            ir,
            proto,
            target_id,
            route_params=_route_params_from_key(proto, routers[frame_router], route_key),
            path=_path_parts(routers[frame_router], route_key),
            route_nodes=[frame_router],
            entries=entries,
        )

    unique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = json.dumps(entry["route_params"], ensure_ascii=False, sort_keys=True)
        existing = unique.get(key)
        if existing is None or len(entry["route_nodes"]) > len(existing["route_nodes"]):
            unique[key] = entry
    return sorted(unique.values(), key=lambda item: (item["route_params"].get("proto", ""), item["path"]))


def _walk(
    ir: dict[str, Any],
    proto: str,
    node_id: str,
    *,
    route_params: dict[str, Any],
    path: list[str],
    route_nodes: list[str],
    entries: list[dict[str, Any]],
) -> None:
    routers = ir.get("routers") or {}
    leaves = ir.get("leaves") or {}
    leaf = leaves.get(node_id)
    if not leaf:
        return

    branch_fields = [
        field for field in leaf.get("fields") or []
        if field.get("type_ref") == "routed_payload"
        and field.get("params", {}).get("router") in routers
    ]
    if branch_fields:
        for field in branch_fields:
            router_id = field.get("params", {}).get("router")
            router = routers[router_id]
            for route_key, target_id in sorted((router.get("route_table") or {}).items()):
                next_params = dict(route_params)
                next_params.update(_route_params_from_key(proto, router, route_key))
                _walk(
                    ir,
                    proto,
                    target_id,
                    route_params=next_params,
                    path=path + _path_parts(router, route_key),
                    route_nodes=route_nodes + [node_id, router_id],
                    entries=entries,
                )
        return

    route_params = _normalize_route_params(proto, route_params)
    leaf_id = node_id
    entry_id = f"{leaf_id}::{_route_signature(route_params)}"
    entries.append({
        "id": entry_id,
        "entry_id": entry_id,
        "leaf_id": leaf_id,
        "name": leaf.get("name") or node_id,
        "description": _description_for_leaf(leaf),
        "route_params": route_params,
        "path": path,
        "route_nodes": route_nodes + [node_id],
        "fields": _leaf_fields(leaf),
        "message_ref": leaf.get("message_ref"),
        "router_id": leaf.get("router_id"),
        "route_key": leaf.get("route_key"),
    })


def _frame_router_id(ir: dict[str, Any]) -> str:
    for field in (ir.get("frame") or {}).get("fields") or []:
        if field.get("type_ref") == "routed_payload":
            return str(field.get("params", {}).get("router") or "")
    return ""


def _route_params_from_key(proto: str, router: dict[str, Any], route_key: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    values = _route_values(route_key)
    for index, key_path in enumerate(router.get("key_paths") or []):
        if index >= len(values):
            continue
        value = values[index]
        leaf = str(key_path).split(".")[-1]
        if leaf == "func":
            result["func"] = _hex_byte(value)
        elif leaf == "afn":
            result["afn"] = _hex_byte(value)
        elif leaf == "di":
            result["di"] = str(value).replace(" ", "").upper()
        elif leaf == "dir":
            result["dir"] = "uplink" if int(value) == 1 else "downlink"
        elif leaf == "add":
            result["has_address"] = bool(int(value))
    return result


def _path_parts(router: dict[str, Any], route_key: str) -> list[str]:
    values = _route_values(route_key)
    parts: list[str] = []
    for index, key_path in enumerate(router.get("key_paths") or []):
        if index >= len(values):
            continue
        parts.append(f"{str(key_path).split('.')[-1]}={_display_value(values[index])}")
    return parts


def _route_values(route_key: str) -> list[Any]:
    try:
        values = json.loads(route_key)
    except (TypeError, json.JSONDecodeError):
        values = [route_key]
    return values if isinstance(values, list) else [values]


def _normalize_route_params(proto: str, params: dict[str, Any]) -> dict[str, Any]:
    short_proto = {"csg_2016": "csg", "dlt645_2007": "dlt645"}.get(proto, proto)
    normalized = {"proto": short_proto}
    for key in ("func", "afn", "di", "dir", "has_address"):
        if key in params:
            normalized[key] = params[key]
    return normalized


def _route_signature(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("dir", "has_address", "func", "afn", "di"):
        if key not in params:
            continue
        name = "add" if key == "has_address" else key
        value = params[key]
        if key == "has_address":
            value = "1" if value else "0"
        parts.append(f"{name}={value}")
    return "::".join(parts)


def _leaf_fields(leaf: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in leaf.get("fields") or []:
        field_type = field.get("type_ref")
        if field_type in {"const", "const_repeat", "checksum", "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8", "routed_payload"}:
            continue
        if field_type == "struct":
            for child in field.get("params", {}).get("fields") or []:
                fields.append(f"{field['name']}.{child.get('name')}")
        else:
            fields.append(str(field.get("name")))
    return fields


def _description_for_leaf(leaf: dict[str, Any]) -> str:
    if leaf.get("description"):
        return str(leaf["description"])
    name = str(leaf.get("name") or leaf.get("id") or "")
    return name.split(".")[-1].replace("_", " ")


def _hex_byte(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:02X}"
    text = str(value).replace("0x", "").replace("0X", "")
    try:
        return f"{int(text, 16):02X}"
    except ValueError:
        return text.upper()


def _display_value(value: Any) -> str:
    if isinstance(value, int):
        return f"0x{value:02X}"
    return str(value)
