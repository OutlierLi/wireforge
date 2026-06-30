"""Stateful MCP workflow for protocol variant extensions (DOCX auto pipeline)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from doc_parser.document_ir import DocumentIR
from extractor.extension_draft import ExtensionDraft

from protocol_extend.schema import (
    ExtensionSpec,
    afn_has_builtin_router,
    missing_fields,
    normalize_protocol,
    router_compile_hint,
)
from doc_parser.metadata_extractor import resolve_afn
from protocol_extend.document_pipeline import (
    batch_summary,
    build_document_catalog,
    catalog_scan_summary,
    chapter_hint_from,
    collect_all_drafts,
    document_path_from,
    load_drafts,
    load_or_parse_document,
    save_drafts,
)
from protocol_extend.validator import find_conflicts
from protocol_extend import yaml_writer
from protocol_extend.fidelity_checker import check_fidelity
from protocol_extend.source_snapshot import freeze_snapshot_if_missing
from protocol_extend.map_verify import (
    refresh_protocol_map,
    verify_extension_routes,
    verify_route_handle,
)
from protocol_extend.fields import process_agent_fields
from protocol_extend.run_log import ExtendRunLog

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "log" / "protocol_extend_runs"
REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
COMPILED_DIR = ROOT / "compiled"

RunState = Literal["INIT", "SUCCEEDED", "FAILED"]


@dataclass
class ExtendRecord:
    run_id: str
    raw_input: str
    state: RunState = "INIT"
    spec: dict[str, Any] = field(default_factory=dict)
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
            "results": self.results,
            "error": self.error,
            "yaml_preview": self.yaml_preview,
            "extension_file": self.extension_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtendRecord:
        return cls(
            run_id=str(data["run_id"]),
            raw_input=str(data.get("raw_input") or ""),
            state=str(data.get("state") or "INIT"),  # type: ignore[arg-type]
            spec=dict(data.get("spec") or {}),
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

    if record.state == "SUCCEEDED":
        return _public_result(record, debug=debug_enabled)

    try:
        _advance(record, user_input or {})
    except Exception as exc:
        record.state = "FAILED"
        record.error = str(exc)

    _save(record)
    return _public_result(record, debug=debug_enabled)


def _advance(record: ExtendRecord, user_input: dict[str, Any]) -> None:
    _merge_run_meta(record, user_input)
    _run_auto_pipeline(record, user_input)


def _run_auto_pipeline(record: ExtendRecord, user_input: dict[str, Any]) -> None:
    run_dir = RUNS_DIR / record.run_id
    log = ExtendRunLog(run_dir)
    record.results["log_dir"] = str(run_dir)
    record.results["log_path"] = str(log.log_path)

    doc_path = document_path_from(record.spec, user_input)
    if not doc_path:
        record.state = "FAILED"
        record.error = "document_path is required (DOCX-only extension pipeline)"
        log.log_stage("failed", {"summary": record.error, "error": record.error})
        return

    try:
        chapter_hint = chapter_hint_from(record.spec, user_input)
        doc_ir = load_or_parse_document(
            doc_path,
            run_dir=run_dir,
            root=ROOT,
            force_reparse=bool(user_input.get("document_path")),
            chapter_hint=chapter_hint,
        )
    except Exception as exc:
        record.state = "FAILED"
        record.error = f"document parse failed: {exc}"
        log.log_stage("failed", {"summary": record.error, "error": record.error})
        return

    catalog = build_document_catalog(doc_ir)
    scan_summary = catalog_scan_summary(catalog)
    record.results["document_ir_path"] = str(run_dir / "document_ir.json")
    record.results["document_ir_summary"] = doc_ir.summary()
    record.results["document_catalog"] = catalog
    record.results["scan_summary"] = scan_summary
    log.log_document_parse(
        document_path=doc_path,
        ir_summary=doc_ir.summary(),
        scan_summary=scan_summary,
    )

    drafts = collect_all_drafts(doc_ir)
    if not drafts:
        record.state = "FAILED"
        record.error = "未能从文档采集任何报文 draft"
        log.log_stage("failed", {"summary": record.error, "error": record.error})
        return

    for draft in drafts:
        if draft.afn is None and draft.di:
            afn, _ = resolve_afn(di=draft.di, text=draft.description or draft.title)
            if afn is not None:
                draft.afn = afn
        freeze_snapshot_if_missing(draft, doc=doc_ir)

    _persist_drafts(record, drafts)
    log.log_document_extract(drafts)

    compile_ok = True
    map_ok = True
    template_only_any = False

    for draft_index, draft in enumerate(drafts):
        ok, draft_compile_ok, draft_map_ok, draft_template_only = _process_draft_auto(
            record, drafts, draft_index, log,
        )
        if draft_template_only:
            template_only_any = True
        if not draft_compile_ok:
            compile_ok = False
        if not draft_map_ok:
            map_ok = False

    _persist_drafts(record, drafts)
    summary = batch_summary(drafts)
    record.results["batch_summary"] = summary
    record.results["compile_ok"] = compile_ok and not template_only_any
    record.results["map_ok"] = map_ok and not template_only_any
    if template_only_any:
        record.results["template_only"] = True

    accepted_files = summary.get("files") or []
    if accepted_files:
        record.extension_file = accepted_files[-1]
        record.results["extension_file"] = accepted_files[-1]

    log.log_batch_complete(summary)

    if summary.get("accepted", 0) > 0:
        record.state = "SUCCEEDED"
        record.error = ""
        record.results["bootstrap_hint"] = record.results.get("router_hint") or (
            "protocol map refreshed; re-run bootstrap only if SVG/cache cleanup needed"
        )
    else:
        record.state = "FAILED"
        record.error = "no drafts accepted; see extend.log and stages/"
        record.results["bootstrap_hint"] = "see log_dir for per-draft errors"


def _process_draft_auto(
    record: ExtendRecord,
    drafts: list[ExtensionDraft],
    draft_index: int,
    log: ExtendRunLog,
) -> tuple[bool, bool, bool, bool]:
    """Process one draft: infer → yaml → fidelity log → auto write. Returns (accepted, compile_ok, map_ok, template_only)."""
    draft = drafts[draft_index]
    spec = draft.to_spec()

    if spec.protocol not in {"csg_2016", "csg"} and normalize_protocol(spec.protocol) != "csg_2016":
        draft.status = "failed"
        draft.last_error = f"unsupported protocol: {spec.protocol}"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return False, True, True, False

    missing = missing_fields(spec)
    if missing:
        draft.status = "failed"
        draft.last_error = f"missing fields: {', '.join(missing)}"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error, extra={"missing": missing})
        return False, True, True, False

    if not (spec.fields or spec.resp_fields):
        draft.status = "failed"
        draft.last_error = "empty payload fields"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return False, True, True, False

    conflicts = find_conflicts(spec)
    if conflicts:
        draft.status = "failed"
        draft.last_error = "DI/route conflict with existing variant"
        record.results["conflicts"] = conflicts[:5]
        log.log_draft_result(
            draft_index, draft, status="failed", error=draft.last_error,
            extra={"conflicts": conflicts[:5]},
        )
        return False, True, True, False

    inference_report, field_type_warnings = _run_inference_for_spec(spec)
    log.log_draft_inference(
        draft_index, draft,
        inference_report=inference_report,
        field_type_warnings=field_type_warnings,
    )

    yaml_text = yaml_writer.render_extension_yaml(spec, record.raw_input)
    rel_path = f"protocol_tool/protocols/csg_2016/variants/extensions/{yaml_writer.extension_filename(spec)}"
    record.yaml_preview = yaml_text
    record.extension_file = rel_path
    log.log_draft_yaml(draft_index, draft, yaml_text=yaml_text, extension_file=rel_path)

    fidelity_report = check_fidelity(draft.source_snapshot, spec, inference_report)
    draft.fidelity_report = fidelity_report
    log.log_draft_fidelity(draft_index, draft, fidelity_report=fidelity_report)

    target = _extensions_dir() / yaml_writer.extension_filename(spec)
    if target.exists():
        draft.status = "failed"
        draft.last_error = f"extension file already exists: {target}"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return False, True, True, False

    try:
        written = yaml_writer.write_extension_file(spec, record.raw_input, _extensions_dir())
    except FileExistsError as exc:
        draft.status = "failed"
        draft.last_error = str(exc)
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return False, True, True, False

    if spec.afn is not None and not afn_has_builtin_router(spec.afn):
        return _finalize_template_only_accept(record, draft, draft_index, spec, written, log)

    compile_ok, map_ok = _compile_and_verify(record, draft, draft_index, spec, written, log)
    return draft.status == "accepted", compile_ok, map_ok, False


def _compile_and_verify(
    record: ExtendRecord,
    draft: ExtensionDraft,
    draft_index: int,
    spec: ExtensionSpec,
    written: Path,
    log: ExtendRunLog,
) -> tuple[bool, bool]:
    def _rollback() -> None:
        if written.exists():
            written.unlink()

    try:
        from protocol_tool.compiler.pipeline import compile_protocol
        compile_protocol(str(REGISTRY), "csg_2016", output_dir=str(COMPILED_DIR))
    except Exception as exc:
        _rollback()
        draft.status = "failed"
        draft.last_error = f"compile failed: {exc}"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return False, False

    variant_ids = [v["id"] for v in yaml_writer.build_variants(spec)]
    try:
        protocol_map = refresh_protocol_map(COMPILED_DIR)
        map_entries, map_errors = verify_extension_routes(spec, variant_ids, protocol_map)
        if map_errors:
            _rollback()
            draft.status = "failed"
            draft.last_error = f"route verification failed: {'; '.join(map_errors)}"
            log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
            return True, False

        route_errors: list[str] = []
        if spec.pair and spec.afn != 0:
            dir_values: list[int | None] = [0, 1]
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
            draft.status = "failed"
            draft.last_error = f"route handle failed: {'; '.join(route_errors)}"
            log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
            return True, False

        rel_written = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)
        draft.status = "accepted"
        draft.extension_file = rel_written
        draft.last_error = ""
        record.results["map_ok"] = True
        record.results["map_files"] = [
            str(COMPILED_DIR / "protocol_map.json"),
            str(COMPILED_DIR / "protocol_map.yaml"),
        ]
        record.results["route_entries"] = [
            {"entry_id": e.get("entry_id"), "description": e.get("description")}
            for e in map_entries
        ]
        record.results["variant_ids"] = variant_ids
        record.results["written_path"] = str(written)
        record.extension_file = rel_written
        log.log_draft_result(
            draft_index, draft, status="accepted",
            extra={"extension_file": rel_written, "variant_ids": variant_ids},
        )
        return True, True
    except Exception as exc:
        _rollback()
        draft.status = "failed"
        draft.last_error = f"map refresh failed: {exc}"
        log.log_draft_result(draft_index, draft, status="failed", error=draft.last_error)
        return True, False


def _finalize_template_only_accept(
    record: ExtendRecord,
    draft: ExtensionDraft,
    draft_index: int,
    spec: ExtensionSpec,
    written: Path,
    log: ExtendRunLog,
) -> tuple[bool, bool, bool, bool]:
    rel_written = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)
    variant_ids = [v["id"] for v in yaml_writer.build_variants(spec)]
    hint = router_compile_hint(spec.afn) if spec.afn is not None else ""

    draft.status = "accepted"
    draft.extension_file = rel_written
    draft.last_error = ""
    record.results["template_only"] = True
    record.results["router_hint"] = hint
    record.results["variant_ids"] = variant_ids
    record.results["written_path"] = str(written)
    record.extension_file = rel_written
    log.log_draft_result(
        draft_index, draft, status="accepted",
        extra={"template_only": True, "router_hint": hint, "extension_file": rel_written},
    )
    return True, False, False, True


def _run_inference_for_spec(spec: ExtensionSpec) -> tuple[list[dict[str, Any]], list[str]]:
    report: list[dict[str, Any]] = []
    warnings: list[str] = []

    if spec.fields:
        _, field_report, field_warnings = process_agent_fields(spec.fields)
        report.extend(field_report)
        warnings.extend(field_warnings)

    if spec.resp_fields:
        _, resp_report, resp_warnings = process_agent_fields(spec.resp_fields)
        for entry in resp_report:
            entry = dict(entry)
            entry["name"] = f"resp.{entry['name']}"
            report.append(entry)
        warnings.extend(resp_warnings)

    return report, warnings


def _persist_drafts(record: ExtendRecord, drafts: list[ExtensionDraft]) -> None:
    record.results["message_drafts"] = [d.to_dict() for d in drafts]
    save_drafts(RUNS_DIR / record.run_id, drafts)


def _merge_run_meta(record: ExtendRecord, user_input: dict[str, Any]) -> None:
    for key in ("document_path", "chapter_hint"):
        if key in user_input and user_input[key] not in (None, ""):
            record.spec[key] = user_input[key]


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
                "Omit run_id for a new task."
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

    out["log_dir"] = record.results.get("log_dir") or str(RUNS_DIR / record.run_id)
    out["log_path"] = record.results.get("log_path") or str(Path(out["log_dir"]) / "extend.log")

    if record.state == "SUCCEEDED":
        out["extension_file"] = record.results.get("extension_file") or record.extension_file
        out["compile_ok"] = record.results.get("compile_ok", False)
        out["map_ok"] = record.results.get("map_ok", False)
        out["bootstrap_hint"] = record.results.get("bootstrap_hint", "")
        if record.results.get("router_hint"):
            out["router_hint"] = record.results["router_hint"]
        if record.results.get("template_only"):
            out["template_only"] = True
        if record.results.get("batch_summary"):
            out["batch_summary"] = record.results["batch_summary"]
            fs = record.results["batch_summary"].get("fidelity_summary")
            if fs:
                out["fidelity_summary"] = fs
        if record.results.get("scan_summary"):
            out["scan_summary"] = record.results["scan_summary"]
    elif record.state == "FAILED":
        if record.results.get("batch_summary"):
            out["batch_summary"] = record.results["batch_summary"]
        if record.results.get("conflicts"):
            out["conflicts"] = record.results["conflicts"]

    return out


def _public_error(message: str, *, debug: bool = False) -> dict[str, Any]:
    out = {"state": "FAILED", "error": message}
    if debug:
        out["debug"] = True
    return out
