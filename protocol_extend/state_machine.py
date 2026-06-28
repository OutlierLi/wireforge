"""Stateful MCP workflow for protocol variant extensions."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from protocol_extend.parser import build_spec
from protocol_extend.schema import (
    AFN_ROUTERS,
    INPUT_SCHEMA,
    UNSUPPORTED_AFN_HINT,
    ExtensionSpec,
    missing_fields,
    normalize_protocol,
    partial_with_defaults,
)
from protocol_extend.fields import FIELD_DSL_EXAMPLES
from protocol_extend.validator import find_conflicts
from protocol_extend import yaml_writer
from protocol_extend.map_verify import (
    refresh_protocol_map,
    verify_extension_routes,
    verify_route_handle,
)

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "log" / "protocol_extend_runs"
REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
COMPILED_DIR = ROOT / "compiled"

RunState = Literal["INIT", "WAITING_INPUT", "SUCCEEDED", "FAILED"]


@dataclass
class ExtendRecord:
    run_id: str
    raw_input: str
    state: RunState = "INIT"
    spec: dict[str, Any] = field(default_factory=dict)
    waiting_input: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    yaml_preview: str = ""
    extension_file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "raw_input": self.raw_input,
            "state": self.state,
            "spec": self.spec,
            "waiting_input": self.waiting_input,
            "results": self.results,
            "error": self.error,
            "yaml_preview": self.yaml_preview,
            "extension_file": self.extension_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtendRecord":
        return cls(
            run_id=str(data["run_id"]),
            raw_input=str(data.get("raw_input") or ""),
            state=str(data.get("state") or "INIT"),  # type: ignore[arg-type]
            spec=dict(data.get("spec") or {}),
            waiting_input=dict(data.get("waiting_input") or {}),
            results=dict(data.get("results") or {}),
            error=str(data.get("error") or ""),
            yaml_preview=str(data.get("yaml_preview") or ""),
            extension_file=str(data.get("extension_file") or ""),
        )


def run_protocol_extend(
    raw_input: str | None = None,
    *,
    run_id: str | None = None,
    user_input: dict[str, Any] | None = None,
    debug: bool | None = None,
) -> dict[str, Any]:
    debug_enabled = _debug_enabled(debug)
    try:
        record = _load_or_create(run_id, raw_input)
    except Exception as exc:
        return _public_error(str(exc), debug=debug_enabled)

    if raw_input and not record.raw_input:
        record.raw_input = raw_input

    try:
        _advance(record, user_input or {})
    except Exception as exc:
        record.state = "FAILED"
        record.error = str(exc)

    _save(record)
    return _public_result(record, debug=debug_enabled)


def _advance(record: ExtendRecord, user_input: dict[str, Any]) -> None:
    spec = _spec_from_record(record, user_input)

    if spec.protocol not in {"csg_2016", "csg"} and normalize_protocol(spec.protocol) != "csg_2016":
        record.state = "FAILED"
        record.error = f"unsupported protocol: {spec.protocol} (v1: csg only)"
        return

    if spec.afn is not None and spec.afn not in AFN_ROUTERS:
        record.state = "FAILED"
        record.error = UNSUPPORTED_AFN_HINT
        return

    missing = missing_fields(spec)
    if "afn_supported" in missing:
        record.state = "FAILED"
        record.error = UNSUPPORTED_AFN_HINT
        return

    if missing:
        _wait_params(record, spec, missing)
        return

    conflicts = find_conflicts(spec)
    if conflicts:
        record.state = "FAILED"
        record.error = "DI/route conflict with existing variant"
        record.results["conflicts"] = conflicts[:5]
        return

    yaml_text = yaml_writer.render_extension_yaml(spec, record.raw_input)
    rel_path = f"protocol_tool/protocols/csg_2016/variants/extensions/{yaml_writer.extension_filename(spec)}"
    record.yaml_preview = yaml_text
    record.extension_file = rel_path
    _store_spec(record, spec)

    if not user_input.get("confirm"):
        record.state = "WAITING_INPUT"
        record.waiting_input = {
            "field": "confirm",
            "need": "confirm",
            "message": "请确认 YAML 预览；确认写入传 user_input.confirm=true",
            "yaml_preview": yaml_text,
            "extension_file": rel_path,
            "variant_ids": [v["id"] for v in yaml_writer.build_variants(spec)],
        }
        return

    target = _extensions_dir() / yaml_writer.extension_filename(spec)
    if target.exists():
        record.state = "FAILED"
        record.error = f"extension file already exists: {target}"
        return

    written = yaml_writer.write_extension_file(spec, record.raw_input, _extensions_dir())
    record.results["written_path"] = str(written)

    def _rollback() -> None:
        if written.exists():
            written.unlink()

    try:
        from protocol_tool.compiler.pipeline import compile_protocol
        compile_protocol(str(REGISTRY), "csg_2016", output_dir=str(COMPILED_DIR))
        record.results["compile_ok"] = True
    except Exception as exc:
        _rollback()
        record.state = "FAILED"
        record.error = f"compile failed: {exc}"
        record.results["compile_ok"] = False
        return

    variant_ids = [v["id"] for v in yaml_writer.build_variants(spec)]
    try:
        protocol_map = refresh_protocol_map(COMPILED_DIR)
        map_entries, map_errors = verify_extension_routes(spec, variant_ids, protocol_map)
        if map_errors:
            _rollback()
            record.state = "FAILED"
            record.error = f"route verification failed: {'; '.join(map_errors)}"
            record.results["map_ok"] = False
            record.results["map_errors"] = map_errors
            return

        route_errors: list[str] = []
        dir_values: list[int | None]
        if spec.pair and spec.afn != 0:
            dir_values = [0, 1]
        elif spec.pair and spec.afn == 0:
            dir_values = [None, None]
        elif spec.afn_uses_dir():
            dir_values = [spec.dir]
        else:
            dir_values = [None]

        for dir_val in dir_values:
            route_result = verify_route_handle(spec, dir_value=dir_val)
            if not route_result.get("success"):
                route_errors.append(str(route_result.get("error") or route_result))

        if route_errors:
            _rollback()
            record.state = "FAILED"
            record.error = f"route handle failed: {'; '.join(route_errors)}"
            record.results["map_ok"] = False
            record.results["route_errors"] = route_errors
            return

        record.results["map_ok"] = True
        record.results["map_files"] = [
            str(COMPILED_DIR / "protocol_map.json"),
            str(COMPILED_DIR / "protocol_map.yaml"),
        ]
        record.results["route_entries"] = [
            {"entry_id": e.get("entry_id"), "description": e.get("description")}
            for e in map_entries
        ]
    except Exception as exc:
        _rollback()
        record.state = "FAILED"
        record.error = f"map refresh failed: {exc}"
        record.results["map_ok"] = False
        return

    record.extension_file = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)

    record.state = "SUCCEEDED"
    record.error = ""
    record.results.update({
        "extension_file": record.extension_file,
        "variant_ids": variant_ids,
        "bootstrap_hint": "protocol map refreshed; re-run bootstrap only if SVG/cache cleanup needed",
    })
    record.waiting_input = {}


def _spec_from_record(record: ExtendRecord, user_input: dict[str, Any]) -> ExtensionSpec:
    base = dict(record.spec)
    merged_input = {**base, **(user_input or {})}
    spec = build_spec(record.raw_input, merged_input)
    return spec


def _store_spec(record: ExtendRecord, spec: ExtensionSpec) -> None:
    record.spec = spec.to_partial()
    if spec.fields:
        record.spec["fields"] = spec.fields
    if spec.resp_fields:
        record.spec["resp_fields"] = spec.resp_fields


def _wait_params(record: ExtendRecord, spec: ExtensionSpec, missing: list[str]) -> None:
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": "params",
        "need": "params",
        "message": "缺少扩展报文必填参数，请补充 dir/add/description 等。",
        "missing_fields": missing,
        "input_schema": INPUT_SCHEMA,
        "field_dsl_examples": FIELD_DSL_EXAMPLES,
        "partial": partial_with_defaults(spec),
    }
    _store_spec(record, spec)


def _extensions_dir() -> Path:
    return yaml_writer.EXTENSIONS_DIR


def _load_or_create(run_id: str | None, raw_input: str | None) -> ExtendRecord:
    rid = run_id or uuid.uuid4().hex
    path = RUNS_DIR / rid / "state.json"
    if path.exists():
        record = ExtendRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if raw_input and raw_input != record.raw_input:
            raise ValueError(
                "run_id belongs to an existing task with different raw_input. "
                "Use user_input to continue, or omit run_id for a new task."
            )
        return record
    if not raw_input:
        raise ValueError("raw_input is required for a new run")
    record = ExtendRecord(run_id=rid, raw_input=raw_input)
    (RUNS_DIR / rid).mkdir(parents=True, exist_ok=True)
    return record


def _save(record: ExtendRecord) -> None:
    path = RUNS_DIR / record.run_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "state.json").write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _debug_enabled(debug: bool | None) -> bool:
    if debug is not None:
        return bool(debug)
    return os.getenv("WIREFORGE_MCP_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def _public_result(record: ExtendRecord, *, debug: bool = False) -> dict[str, Any]:
    if debug:
        return record.to_dict()

    out: dict[str, Any] = {"run_id": record.run_id, "state": record.state}
    if record.error:
        out["error"] = record.error

    if record.state == "WAITING_INPUT":
        wi = record.waiting_input
        need = wi.get("need") or wi.get("field") or "params"
        out["need"] = need
        if need == "params":
            out["missing_fields"] = wi.get("missing_fields") or []
            out["partial"] = wi.get("partial") or {}
            out["input_schema"] = wi.get("input_schema") or INPUT_SCHEMA
            out["field_dsl_examples"] = wi.get("field_dsl_examples") or FIELD_DSL_EXAMPLES
        elif need == "confirm":
            out["yaml_preview"] = wi.get("yaml_preview") or record.yaml_preview
            out["extension_file"] = wi.get("extension_file") or record.extension_file
            out["variant_ids"] = wi.get("variant_ids") or []
    elif record.state == "SUCCEEDED":
        out["extension_file"] = record.results.get("extension_file") or record.extension_file
        out["compile_ok"] = record.results.get("compile_ok", True)
        out["map_ok"] = record.results.get("map_ok", False)
        out["map_files"] = record.results.get("map_files") or []
        out["variant_ids"] = record.results.get("variant_ids") or []
        out["route_entries"] = record.results.get("route_entries") or []
        out["bootstrap_hint"] = record.results.get("bootstrap_hint", "")
    elif record.results.get("conflicts"):
        out["conflicts"] = record.results["conflicts"]

    return out


def _public_error(message: str, *, debug: bool = False) -> dict[str, Any]:
    out = {"state": "FAILED", "error": message}
    if debug:
        out["debug"] = True
    return out
