"""Stateful MCP workflow for protocol variant extensions."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from doc_parser.document_ir import DocumentIR
from extractor.extension_draft import ExtensionDraft

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
from doc_parser.metadata_extractor import resolve_afn
from protocol_extend.fields import FIELD_DSL_EXAMPLES, process_agent_fields
from protocol_extend.document_pipeline import (
    batch_summary,
    build_agent_context,
    build_document_catalog,
    catalog_scan_summary,
    chapter_hint_from,
    collect_all_drafts,
    collection_summary,
    document_path_from,
    draft_from_user_input,
    load_drafts,
    load_or_parse_document,
    review_progress,
    save_drafts,
)
from protocol_extend.validator import find_conflicts
from protocol_extend import yaml_writer
from protocol_extend.fidelity_checker import accept_allowed, check_fidelity, fidelity_preview
from protocol_extend.source_snapshot import freeze_snapshot_if_missing, source_excerpt
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
Phase = Literal["collection", "review"]


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
    def from_dict(cls, data: dict[str, Any]) -> ExtendRecord:
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
    _merge_run_meta(record, user_input)
    action = _normalize_action(user_input)
    phase: Phase = record.results.get("phase") or "collection"

    if phase == "collection":
        _run_collection_phase(record, user_input, action)
        return

    _run_review_phase(record, user_input, action)


def _run_collection_phase(
    record: ExtendRecord,
    user_input: dict[str, Any],
    action: str | None,
) -> None:
    run_dir = RUNS_DIR / record.run_id
    spec = _spec_from_record(record, user_input)
    doc_path = document_path_from(record.spec, user_input)
    doc_ir: DocumentIR | None = None

    if doc_path:
        try:
            chapter_hint = chapter_hint_from(record.spec, user_input)
            doc_ir = load_or_parse_document(
                doc_path,
                run_dir=run_dir,
                root=ROOT,
                force_reparse=bool(user_input.get("document_path")),
                chapter_hint=chapter_hint,
            )
            record.results["document_ir_path"] = str(run_dir / "document_ir.json")
            record.results["document_ir_summary"] = doc_ir.summary()
            catalog = build_document_catalog(doc_ir)
            record.results["document_catalog"] = catalog
            record.results["scan_summary"] = catalog_scan_summary(catalog)
        except Exception as exc:
            record.state = "FAILED"
            record.error = f"document parse failed: {exc}"
            return

    drafts = _load_drafts_record(record)
    if not drafts:
        if doc_ir is not None:
            drafts = collect_all_drafts(doc_ir)
        else:
            drafts = [draft_from_user_input(spec)]
        if not drafts:
            record.state = "FAILED"
            record.error = "未能从输入或文档采集任何报文 draft"
            return
        _persist_drafts(record, drafts)

    collection_index = int(record.results.get("collection_draft_index") or 0)
    if collection_index < len(drafts):
        drafts[collection_index].merge_user_input(user_input)
        _persist_drafts(record, drafts)

    if spec.protocol not in {"csg_2016", "csg"} and normalize_protocol(spec.protocol) != "csg_2016":
        record.state = "FAILED"
        record.error = f"unsupported protocol: {spec.protocol} (v1: csg only)"
        return

    while collection_index < len(drafts):
        draft = drafts[collection_index]
        if draft.afn is not None and draft.afn not in AFN_ROUTERS:
            record.state = "FAILED"
            record.error = UNSUPPORTED_AFN_HINT
            return

        if draft.afn is None and draft.di:
            afn, _ = resolve_afn(di=draft.di, text=draft.description or draft.title)
            if afn is not None:
                draft.afn = afn
                _persist_drafts(record, drafts)

        draft_spec = draft.to_spec()
        missing = missing_fields(draft_spec)
        if "afn_supported" in missing:
            record.state = "FAILED"
            record.error = UNSUPPORTED_AFN_HINT
            return

        if missing:
            record.results["collection_draft_index"] = collection_index
            _wait_params(record, draft_spec, missing, phase="collection", draft_index=collection_index)
            return

        if (
            doc_path
            and not (draft.fields or draft.resp_fields)
            and not user_input.get("allow_empty_fields")
            and record.waiting_input.get("need") != "fields"
        ):
            record.results["collection_draft_index"] = collection_index
            _wait_fields_empty(
                record,
                draft_spec,
                {"section_id": draft.section_id, "extraction_report": draft.extraction_report},
                phase="collection",
                draft_index=collection_index,
            )
            return

        freeze_snapshot_if_missing(draft)

        collection_index += 1
        record.results["collection_draft_index"] = collection_index

    for d in drafts:
        freeze_snapshot_if_missing(d)
    _persist_drafts(record, drafts)

    if action == "start":
        record.results["phase"] = "review"
        record.results["draft_index"] = _next_pending_index(drafts, 0)
        record.waiting_input = {}
        _run_review_phase(record, user_input, action=None)
        return

    _wait_collection_ready(record, drafts, doc_path)


def _run_review_phase(
    record: ExtendRecord,
    user_input: dict[str, Any],
    action: str | None,
) -> None:
    drafts = _load_drafts_record(record)
    if not drafts:
        record.state = "FAILED"
        record.error = "no message drafts; restart collection phase"
        return

    draft_index = int(user_input.get("draft_index") if user_input.get("draft_index") is not None else record.results.get("draft_index") or 0)
    draft_index = max(0, min(draft_index, len(drafts) - 1)) if drafts else 0
    record.results["phase"] = "review"
    record.results["draft_index"] = draft_index

    if drafts and draft_index < len(drafts):
        drafts[draft_index].merge_user_input(user_input)
        _persist_drafts(record, drafts)

    if action in ("accept", "skip", "modify"):
        draft = drafts[draft_index]
        if action == "skip":
            draft.status = "skipped"
            draft.skip_reason = str(user_input.get("skip_reason") or "")
            _persist_drafts(record, drafts)
            record.results["draft_index"] = _next_pending_index(drafts, draft_index + 1)
            if record.results["draft_index"] >= len(drafts):
                _finish_batch(record, drafts)
                return
            record.waiting_input = {}
            action = None
        elif action == "modify":
            _apply_modify(draft, user_input)
            _persist_drafts(record, drafts)
            record.waiting_input = {}
            action = None
        elif action == "accept":
            ok = _accept_current_draft(record, drafts, draft_index, user_input)
            if not ok:
                return
            record.results["draft_index"] = _next_pending_index(drafts, draft_index + 1)
            if record.results["draft_index"] >= len(drafts):
                _finish_batch(record, drafts)
                return
            record.waiting_input = {}
            action = None

    while True:
        draft_index = int(record.results.get("draft_index") or 0)
        if draft_index >= len(drafts):
            _finish_batch(record, drafts)
            return

        draft = drafts[draft_index]
        if draft.status in ("accepted", "skipped"):
            record.results["draft_index"] = _next_pending_index(drafts, draft_index + 1)
            continue

        spec = draft.to_spec()
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
            _wait_params(record, spec, missing, phase="review", draft_index=draft_index)
            return

        conflicts = find_conflicts(spec)
        if conflicts:
            draft.last_error = "DI/route conflict with existing variant"
            _persist_drafts(record, drafts)
            record.state = "WAITING_INPUT"
            record.error = draft.last_error
            record.results["conflicts"] = conflicts[:5]
            _wait_message_review(
                record,
                draft,
                drafts,
                draft_index,
                yaml_text=record.yaml_preview or "",
                inference_report=[],
                field_type_warnings=[],
                conflict_error=draft.last_error,
            )
            return

        inference_report, field_type_warnings = _run_inference_for_spec(record, spec)

        from_doc = bool(draft.section_id or document_path_from(record.spec, user_input))
        if (
            from_doc
            and not (spec.fields or spec.resp_fields)
            and not user_input.get("allow_empty_fields")
            and record.waiting_input.get("need") != "fields"
        ):
            _wait_fields_empty(
                record,
                spec,
                {"section_id": draft.section_id, "extraction_report": draft.extraction_report},
                phase="review",
                draft_index=draft_index,
            )
            return

        if (
            field_type_warnings
            and _has_unknown_warnings(inference_report)
            and action != "accept"
            and record.waiting_input.get("need") != "field_types"
            and not user_input.get("force_field_types")
        ):
            doc_ir = _load_doc_ir_if_any(record)
            _wait_field_types(
                record,
                spec,
                inference_report,
                field_type_warnings,
                doc_ir=doc_ir,
                draft_index=draft_index,
                draft=draft,
                drafts=drafts,
            )
            return

        yaml_text = yaml_writer.render_extension_yaml(spec, record.raw_input)
        rel_path = f"protocol_tool/protocols/csg_2016/variants/extensions/{yaml_writer.extension_filename(spec)}"
        record.yaml_preview = yaml_text
        record.extension_file = rel_path

        draft.fidelity_report = check_fidelity(
            draft.source_snapshot,
            spec,
            inference_report,
        )

        _wait_message_review(
            record,
            draft,
            drafts,
            draft_index,
            yaml_text=yaml_text,
            inference_report=inference_report,
            field_type_warnings=field_type_warnings,
        )
        return


def _variant_plan(spec: ExtensionSpec) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for variant in yaml_writer.build_variants(spec):
        match = variant.get("match") or {}
        body = variant.get("body") or {}
        plan.append({
            "id": variant.get("id"),
            "description": variant.get("description"),
            "dir": match.get("control.dir"),
            "add": match.get("control.add"),
            "fields_count": len(body.get("fields") or []),
        })
    return plan


def _accept_current_draft(
    record: ExtendRecord,
    drafts: list[ExtensionDraft],
    draft_index: int,
    user_input: dict[str, Any] | None = None,
) -> bool:
    user_input = user_input or {}
    draft = drafts[draft_index]
    spec = draft.to_spec()

    conflicts = find_conflicts(spec)
    if conflicts:
        draft.last_error = "DI/route conflict with existing variant"
        draft.status = "failed"
        _persist_drafts(record, drafts)
        record.results["conflicts"] = conflicts[:5]
        record.state = "WAITING_INPUT"
        record.error = draft.last_error
        _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
        return False

    target = _extensions_dir() / yaml_writer.extension_filename(spec)
    if target.exists():
        draft.last_error = f"extension file already exists: {target}"
        draft.status = "failed"
        _persist_drafts(record, drafts)
        record.state = "WAITING_INPUT"
        record.error = draft.last_error
        _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
        return False

    inference_report, _ = _run_inference_for_spec(record, spec)
    fidelity_report = check_fidelity(draft.source_snapshot, spec, inference_report)
    draft.fidelity_report = fidelity_report

    force = bool(user_input.get("force_fidelity"))
    if not accept_allowed(fidelity_report, force=force):
        draft.last_error = f"fidelity below threshold: {fidelity_report.get('summary')}"
        _persist_drafts(record, drafts)
        record.state = "WAITING_INPUT"
        record.error = draft.last_error
        yaml_text = record.yaml_preview or yaml_writer.render_extension_yaml(spec, record.raw_input)
        _wait_message_review(
            record,
            draft,
            drafts,
            draft_index,
            yaml_text=yaml_text,
            inference_report=inference_report,
            field_type_warnings=[],
            conflict_error=draft.last_error,
            fidelity_blocked=True,
        )
        return False

    if force and fidelity_report.get("confidence") != "high":
        draft.modify_history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": "force_fidelity accept",
            "fidelity_confidence": fidelity_report.get("confidence"),
            "fidelity_score": fidelity_report.get("score"),
        })

    written = yaml_writer.write_extension_file(spec, record.raw_input, _extensions_dir())

    def _rollback() -> None:
        if written.exists():
            written.unlink()

    try:
        from protocol_tool.compiler.pipeline import compile_protocol
        compile_protocol(str(REGISTRY), "csg_2016", output_dir=str(COMPILED_DIR))
    except Exception as exc:
        _rollback()
        draft.last_error = f"compile failed: {exc}"
        draft.status = "failed"
        _persist_drafts(record, drafts)
        record.state = "WAITING_INPUT"
        record.error = draft.last_error
        _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
        return False

    variant_ids = [v["id"] for v in yaml_writer.build_variants(spec)]
    try:
        protocol_map = refresh_protocol_map(COMPILED_DIR)
        map_entries, map_errors = verify_extension_routes(spec, variant_ids, protocol_map)
        if map_errors:
            _rollback()
            draft.last_error = f"route verification failed: {'; '.join(map_errors)}"
            draft.status = "failed"
            _persist_drafts(record, drafts)
            record.state = "WAITING_INPUT"
            record.error = draft.last_error
            _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
            return False

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
            draft.last_error = f"route handle failed: {'; '.join(route_errors)}"
            draft.status = "failed"
            _persist_drafts(record, drafts)
            record.state = "WAITING_INPUT"
            record.error = draft.last_error
            _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
            return False

        rel_written = str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)
        draft.status = "accepted"
        draft.extension_file = rel_written
        draft.last_error = ""
        _persist_drafts(record, drafts)

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
        record.error = ""
        return True
    except Exception as exc:
        _rollback()
        draft.last_error = f"map refresh failed: {exc}"
        draft.status = "failed"
        _persist_drafts(record, drafts)
        record.state = "WAITING_INPUT"
        record.error = draft.last_error
        _wait_message_review(record, draft, drafts, draft_index, yaml_text=record.yaml_preview or "", inference_report=[], field_type_warnings=[], conflict_error=draft.last_error)
        return False


def _finish_batch(record: ExtendRecord, drafts: list[ExtensionDraft]) -> None:
    summary = batch_summary(drafts)
    record.results["batch_summary"] = summary
    record.state = "SUCCEEDED"
    record.error = ""
    record.waiting_input = {}
    accepted_files = summary.get("files") or []
    if accepted_files:
        record.extension_file = accepted_files[-1]
        record.results["extension_file"] = accepted_files[-1]
    record.results["compile_ok"] = True
    record.results["bootstrap_hint"] = "protocol map refreshed; re-run bootstrap only if SVG/cache cleanup needed"


def _apply_modify(draft: ExtensionDraft, user_input: dict[str, Any]) -> None:
    entry: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": str(user_input.get("modify_reason") or ""),
    }
    patch_keys = [k for k in ("fields", "resp_fields", "dir", "add", "description", "afn", "di", "pair", "resp_description") if k in user_input]
    if patch_keys:
        entry["patch_keys"] = patch_keys
    if user_input.get("fields") is not None:
        entry["fields_patch"] = user_input["fields"]
    draft.modify_history.append(entry)
    draft.merge_user_input(user_input)
    draft.status = "pending"
    draft.last_error = ""


def _wait_collection_ready(
    record: ExtendRecord,
    drafts: list[ExtensionDraft],
    doc_path: str | None,
) -> None:
    record.state = "WAITING_INPUT"
    entries = [d.to_collection_entry() for d in drafts]
    record.waiting_input = {
        "field": "action",
        "need": "collection_ready",
        "phase": "collection",
        "message": (
            f"已从{'文档' if doc_path else '输入'}采集 {len(drafts)} 条报文原始信息（DI/数据域等）。"
            "请向用户展示摘要表，确认后传 user_input.action=start 进入逐条扩展。"
        ),
        "message_drafts": entries,
        "collection_summary": collection_summary(drafts),
        "document_path": doc_path,
        "scan_summary": record.results.get("scan_summary"),
        "document_ir_summary": record.results.get("document_ir_summary"),
    }
    record.results["phase"] = "collection"


def _wait_message_review(
    record: ExtendRecord,
    draft: ExtensionDraft,
    drafts: list[ExtensionDraft],
    draft_index: int,
    *,
    yaml_text: str,
    inference_report: list[dict[str, Any]],
    field_type_warnings: list[str],
    conflict_error: str = "",
    fidelity_blocked: bool = False,
) -> None:
    rel_path = ""
    variant_ids: list[str] = []
    spec = draft.to_spec()
    if yaml_text:
        rel_path = f"protocol_tool/protocols/csg_2016/variants/extensions/{yaml_writer.extension_filename(spec)}"
        variant_ids = [v["id"] for v in yaml_writer.build_variants(spec)]

    fidelity_report = draft.fidelity_report or {}
    if yaml_text and not fidelity_report:
        fidelity_report = check_fidelity(draft.source_snapshot, spec, inference_report)
        draft.fidelity_report = fidelity_report

    record.state = "WAITING_INPUT"
    current = draft.to_collection_entry()
    current["modify_history"] = list(draft.modify_history)
    current["last_error"] = draft.last_error or conflict_error or None
    record.waiting_input = {
        "field": "action",
        "need": "message_review",
        "message": (
            "请向用户展示 source_excerpt、yaml_preview、fidelity_preview，并询问："
            "接受(accept) / 跳过(skip) / 修改(modify)。"
            "fidelity 非 high 时 accept 将被阻断，可 modify 或 force_fidelity。"
        ),
        "current_draft": current,
        "yaml_preview": yaml_text,
        "extension_file": rel_path or record.extension_file,
        "variant_ids": variant_ids,
        "variant_plan": _variant_plan(spec),
        "inference_report": inference_report,
        "field_type_warnings": field_type_warnings,
        "progress": review_progress(drafts, draft_index),
        "available_actions": ["accept", "skip", "modify"],
        "modify_history": list(draft.modify_history),
        "field_details": list(draft.fields),
        "resp_field_details": list(draft.resp_fields),
        "source_excerpt": source_excerpt(draft.source_snapshot) if draft.source_snapshot else {},
        "fidelity_report": fidelity_report,
        "fidelity_preview": fidelity_preview(fidelity_report) if fidelity_report else {},
        "fidelity_blocked": fidelity_blocked,
    }
    if conflict_error or draft.last_error:
        record.waiting_input["last_error"] = conflict_error or draft.last_error


def _wait_fields_empty(
    record: ExtendRecord,
    spec: ExtensionSpec,
    extraction_report: dict[str, Any],
    *,
    phase: Phase,
    draft_index: int,
) -> None:
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": "fields",
        "need": "fields",
        "phase": phase,
        "draft_index": draft_index,
        "message": (
            "未能自动提取 payload 字段。请补充 user_input.fields，"
            "或传 allow_empty_fields=true 确认空字段扩展。"
        ),
        "extraction_report": extraction_report,
        "partial": partial_with_defaults(spec),
        "field_dsl_examples": FIELD_DSL_EXAMPLES,
    }


def _wait_field_types(
    record: ExtendRecord,
    spec: ExtensionSpec,
    inference_report: list[dict[str, Any]],
    field_type_warnings: list[str],
    *,
    doc_ir: DocumentIR | None = None,
    draft_index: int = 0,
    draft: ExtensionDraft | None = None,
    drafts: list[ExtensionDraft] | None = None,
) -> None:
    yaml_text = yaml_writer.render_extension_yaml(spec, record.raw_input)
    rel_path = f"protocol_tool/protocols/csg_2016/variants/extensions/{yaml_writer.extension_filename(spec)}"
    record.yaml_preview = yaml_text
    record.extension_file = rel_path
    record.state = "WAITING_INPUT"
    agent_context = build_agent_context(spec.fields or [], doc_ir, inference_report)
    fidelity_report = check_fidelity(draft.source_snapshot, spec, inference_report) if draft else {}
    if draft:
        draft.fidelity_report = fidelity_report
    record.waiting_input = {
        "field": "field_types",
        "need": "field_types",
        "phase": "review",
        "draft_index": draft_index,
        "message": (
            "部分字段 semantic_type 未能自动推断（unknown）。"
            "可补充 evidence / semantic_override 后 action=modify，或 action=accept 强制接受。"
        ),
        "inference_report": inference_report,
        "field_type_warnings": field_type_warnings,
        "yaml_preview": yaml_text,
        "extension_file": rel_path,
        "variant_ids": [v["id"] for v in yaml_writer.build_variants(spec)],
        "variant_plan": _variant_plan(spec),
        "field_dsl_examples": FIELD_DSL_EXAMPLES,
        "current_draft": draft.to_collection_entry() if draft else None,
        "progress": review_progress(drafts or [], draft_index) if drafts else None,
        "field_details": list(draft.fields) if draft else [],
        "resp_field_details": list(draft.resp_fields) if draft else [],
        "source_excerpt": source_excerpt(draft.source_snapshot) if draft and draft.source_snapshot else {},
        "fidelity_report": fidelity_report,
        "fidelity_preview": fidelity_preview(fidelity_report) if fidelity_report else {},
    }
    if agent_context:
        record.waiting_input["agent_context"] = agent_context


def _run_inference_for_spec(
    record: ExtendRecord,
    spec: ExtensionSpec,
) -> tuple[list[dict[str, Any]], list[str]]:
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

    record.results["inference_report"] = report
    return report, warnings


def _has_unknown_warnings(inference_report: list[dict[str, Any]]) -> bool:
    return any(entry.get("semantic_type") == "unknown" for entry in inference_report)


def _wait_params(
    record: ExtendRecord,
    spec: ExtensionSpec,
    missing: list[str],
    *,
    phase: Phase,
    draft_index: int,
) -> None:
    record.state = "WAITING_INPUT"
    record.waiting_input = {
        "field": "params",
        "need": "params",
        "phase": phase,
        "draft_index": draft_index,
        "message": "缺少扩展报文必填参数，请补充 dir/add/description 等。",
        "missing_fields": missing,
        "input_schema": INPUT_SCHEMA,
        "field_dsl_examples": FIELD_DSL_EXAMPLES,
        "partial": partial_with_defaults(spec),
    }


def _normalize_action(user_input: dict[str, Any]) -> str | None:
    action = user_input.get("action")
    if action is not None:
        return str(action).strip().lower()
    if user_input.get("confirm"):
        return "accept"
    return None


def _next_pending_index(drafts: list[ExtensionDraft], start: int) -> int:
    for idx in range(start, len(drafts)):
        if drafts[idx].status == "pending":
            return idx
    return len(drafts)


def _load_drafts_record(record: ExtendRecord) -> list[ExtensionDraft]:
    run_dir = RUNS_DIR / record.run_id
    drafts = load_drafts(run_dir)
    if drafts:
        record.results["message_drafts"] = [d.to_dict() for d in drafts]
        return drafts
    raw = record.results.get("message_drafts")
    if isinstance(raw, list) and raw:
        return [ExtensionDraft.from_dict(item) for item in raw]
    return []


def _persist_drafts(record: ExtendRecord, drafts: list[ExtensionDraft]) -> None:
    record.results["message_drafts"] = [d.to_dict() for d in drafts]
    save_drafts(RUNS_DIR / record.run_id, drafts)


def _load_doc_ir_if_any(record: ExtendRecord) -> DocumentIR | None:
    doc_path = document_path_from(record.spec, {})
    if not doc_path:
        return None
    ir_path = RUNS_DIR / record.run_id / "document_ir.json"
    if not ir_path.exists():
        return None
    return DocumentIR.from_dict(json.loads(ir_path.read_text(encoding="utf-8")))


def _spec_from_record(record: ExtendRecord, user_input: dict[str, Any]) -> ExtensionSpec:
    base = dict(record.spec)
    merged_input = {**base, **(user_input or {})}
    return build_spec(record.raw_input, merged_input)


def _merge_run_meta(record: ExtendRecord, user_input: dict[str, Any]) -> None:
    for key in ("document_path", "section_id", "chapter_hint", "candidate_id", "di"):
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
            if wi.get("phase"):
                out["phase"] = wi["phase"]
            if wi.get("draft_index") is not None:
                out["draft_index"] = wi["draft_index"]
        elif need == "fields":
            out["message"] = wi.get("message") or ""
            out["extraction_report"] = wi.get("extraction_report") or record.results.get("extraction_report") or {}
            out["partial"] = wi.get("partial") or {}
            out["field_dsl_examples"] = wi.get("field_dsl_examples") or FIELD_DSL_EXAMPLES
            if wi.get("phase"):
                out["phase"] = wi["phase"]
            if wi.get("draft_index") is not None:
                out["draft_index"] = wi["draft_index"]
        elif need == "collection_ready":
            out["message_drafts"] = wi.get("message_drafts") or []
            out["collection_summary"] = wi.get("collection_summary") or {}
            out["message"] = wi.get("message") or ""
            out["phase"] = wi.get("phase") or record.results.get("phase") or "collection"
            if wi.get("document_path"):
                out["document_path"] = wi["document_path"]
            if wi.get("scan_summary"):
                out["scan_summary"] = wi["scan_summary"]
            if wi.get("document_ir_summary"):
                out["document_ir_summary"] = wi["document_ir_summary"]
        elif need == "message_review":
            out["current_draft"] = wi.get("current_draft") or {}
            out["yaml_preview"] = wi.get("yaml_preview") or record.yaml_preview
            out["extension_file"] = wi.get("extension_file") or record.extension_file
            out["variant_ids"] = wi.get("variant_ids") or []
            out["variant_plan"] = wi.get("variant_plan") or []
            out["progress"] = wi.get("progress") or {}
            out["available_actions"] = wi.get("available_actions") or ["accept", "skip", "modify"]
            out["message"] = wi.get("message") or ""
            out["phase"] = "review"
            if wi.get("inference_report"):
                out["inference_report"] = wi["inference_report"]
            if wi.get("field_type_warnings"):
                out["field_type_warnings"] = wi["field_type_warnings"]
            if wi.get("modify_history"):
                out["modify_history"] = wi["modify_history"]
            if wi.get("last_error"):
                out["last_error"] = wi["last_error"]
            if wi.get("source_excerpt"):
                out["source_excerpt"] = wi["source_excerpt"]
            if wi.get("fidelity_report"):
                out["fidelity_report"] = wi["fidelity_report"]
            if wi.get("fidelity_preview"):
                out["fidelity_preview"] = wi["fidelity_preview"]
            if wi.get("fidelity_blocked"):
                out["fidelity_blocked"] = wi["fidelity_blocked"]
            if "fidelity below threshold" in (record.error or ""):
                out["fidelity_blocked"] = True
            if wi.get("field_details") is not None:
                out["field_details"] = wi["field_details"]
            if wi.get("resp_field_details") is not None:
                out["resp_field_details"] = wi["resp_field_details"]
        elif need == "confirm":
            out["yaml_preview"] = wi.get("yaml_preview") or record.yaml_preview
            out["extension_file"] = wi.get("extension_file") or record.extension_file
            out["variant_ids"] = wi.get("variant_ids") or []
            if wi.get("inference_report"):
                out["inference_report"] = wi["inference_report"]
            if wi.get("field_type_warnings"):
                out["field_type_warnings"] = wi["field_type_warnings"]
        elif need == "field_types":
            out["inference_report"] = wi.get("inference_report") or []
            out["field_type_warnings"] = wi.get("field_type_warnings") or []
            out["yaml_preview"] = wi.get("yaml_preview") or record.yaml_preview
            out["extension_file"] = wi.get("extension_file") or record.extension_file
            out["variant_ids"] = wi.get("variant_ids") or []
            out["variant_plan"] = wi.get("variant_plan") or []
            out["field_dsl_examples"] = wi.get("field_dsl_examples") or FIELD_DSL_EXAMPLES
            out["message"] = wi.get("message") or ""
            out["phase"] = "review"
            if wi.get("agent_context"):
                out["agent_context"] = wi["agent_context"]
            if wi.get("current_draft"):
                out["current_draft"] = wi["current_draft"]
            if wi.get("progress"):
                out["progress"] = wi["progress"]
            if wi.get("source_excerpt"):
                out["source_excerpt"] = wi["source_excerpt"]
            if wi.get("fidelity_report"):
                out["fidelity_report"] = wi["fidelity_report"]
            if wi.get("fidelity_preview"):
                out["fidelity_preview"] = wi["fidelity_preview"]
            if wi.get("field_details") is not None:
                out["field_details"] = wi["field_details"]
            if wi.get("resp_field_details") is not None:
                out["resp_field_details"] = wi["resp_field_details"]
        elif need in ("document_scan", "select_message"):
            out["document_path"] = wi.get("document_path") or record.spec.get("document_path")
            out["message_candidates"] = wi.get("message_candidates") or wi.get("document_catalog") or []
            out["document_catalog"] = wi.get("document_catalog") or out["message_candidates"]
            out["scan_summary"] = wi.get("scan_summary") or record.results.get("scan_summary")
            out["document_ir_summary"] = wi.get("document_ir_summary") or record.results.get("document_ir_summary")
            out["message"] = wi.get("message") or ""
    elif record.state == "SUCCEEDED":
        out["extension_file"] = record.results.get("extension_file") or record.extension_file
        out["compile_ok"] = record.results.get("compile_ok", True)
        out["map_ok"] = record.results.get("map_ok", False)
        out["map_files"] = record.results.get("map_files") or []
        out["variant_ids"] = record.results.get("variant_ids") or []
        out["route_entries"] = record.results.get("route_entries") or []
        out["bootstrap_hint"] = record.results.get("bootstrap_hint", "")
        if record.results.get("batch_summary"):
            out["batch_summary"] = record.results["batch_summary"]
            fs = record.results["batch_summary"].get("fidelity_summary")
            if fs:
                out["fidelity_summary"] = fs
    elif record.results.get("conflicts"):
        out["conflicts"] = record.results["conflicts"]

    return out


def _public_error(message: str, *, debug: bool = False) -> dict[str, Any]:
    out = {"state": "FAILED", "error": message}
    if debug:
        out["debug"] = True
    return out
