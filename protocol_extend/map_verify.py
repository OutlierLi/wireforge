"""Refresh protocol map and verify extension routes after compile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_protocol.protocol_map import refresh_protocol_map_cache
from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent


def refresh_protocol_map(compiled_dir: Path) -> dict[str, Any]:
    return refresh_protocol_map_cache(compiled_dir)


def route_params_for(spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "proto": "csg",
        "afn": f"{spec.afn:02X}" if spec.afn is not None else "",
        "di": spec.di.upper(),
    }
    if dir_value is not None:
        params["dir"] = "downlink" if dir_value == 0 else "uplink"
    if spec.add is not None:
        params["has_address"] = spec.add
    return params


def expected_route_param_sets(spec: ExtensionSpec) -> list[dict[str, Any]]:
    if spec.pair:
        if spec.afn == 0:
            base = route_params_for(spec, dir_value=None)
            return [base, base]
        return [
            route_params_for(spec, dir_value=0),
            route_params_for(spec, dir_value=1),
        ]
    dir_val = spec.dir if spec.afn_uses_dir() else None
    return [route_params_for(spec, dir_value=dir_val)]


def find_map_entry_for_variant(
    protocol_map: dict[str, Any],
    variant_id: str,
    route_params: dict[str, Any],
) -> dict[str, Any] | None:
    by_variant: dict[str, Any] | None = None
    by_route: dict[str, Any] | None = None
    for proto in (protocol_map.get("protocols") or {}).values():
        for entry in proto.get("entries") or []:
            leaf_id = str(entry.get("leaf_id") or entry.get("id") or "")
            entry_id = str(entry.get("entry_id") or "")
            if variant_id in leaf_id or variant_id in entry_id:
                by_variant = dict(entry)
            params = entry.get("route_params") or {}
            if all(params.get(key) == value for key, value in route_params.items()):
                if by_route is None:
                    by_route = dict(entry)
    if by_variant is not None:
        params = by_variant.get("route_params") or {}
        if all(params.get(key) == value for key, value in route_params.items()):
            return by_variant
    return by_route


def verify_extension_routes(
    spec: ExtensionSpec,
    variant_ids: list[str],
    protocol_map: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return matched map entries and error messages for missing routes."""
    found: list[dict[str, Any]] = []
    errors: list[str] = []

    expected_sets = expected_route_param_sets(spec)
    if len(expected_sets) != len(variant_ids):
        errors.append("variant count mismatch for route verification")
        return found, errors

    for variant_id, route_params in zip(variant_ids, expected_sets):
        entry = find_map_entry_for_variant(protocol_map, variant_id, route_params)
        if entry is None:
            errors.append(
                f"route not found for {variant_id}: {route_params}"
            )
            continue
        found.append(entry)

    return found, errors


def verify_route_handle(spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
    from console.handlers.route import handle as route_handle

    args: dict[str, Any] = {"proto": "csg", "afn": f"{spec.afn:02X}", "di": spec.di}
    if dir_value is not None:
        args["dir"] = "downlink" if dir_value == 0 else "uplink"
    if spec.add is not None:
        args["has_address"] = spec.add
    return route_handle(args)
