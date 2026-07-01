"""Structured stage logging for protocol extension runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extractor.extension_draft import ExtensionDraft
from protocol_extend.schema import ExtensionSpec
from protocol_extend.source_snapshot import source_excerpt


class ExtendRunLog:
    """Write per-stage artifacts under ``log/protocol_extend_runs/<run_id>/``."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "extend.log"
        self.stages_dir = self.run_dir / "stages"
        self.stages_dir.mkdir(parents=True, exist_ok=True)
        self._stage_index = 0

    def log_line(self, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")

    def log_stage(self, stage: str, payload: dict[str, Any]) -> Path:
        self._stage_index += 1
        entry = {
            "stage": stage,
            "index": self._stage_index,
            "at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        path = self.stages_dir / f"{self._stage_index:03d}_{stage}.json"
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = payload.get("summary") or payload.get("message") or stage
        self.log_line(f"{stage}: {summary}")
        return path

    def log_document_parse(
        self,
        *,
        document_path: str,
        ir_summary: dict[str, Any] | None,
        scan_summary: dict[str, Any] | None,
    ) -> None:
        self.log_stage(
            "document_parse",
            {
                "summary": f"parsed {document_path}",
                "document_path": document_path,
                "document_ir_summary": ir_summary or {},
                "scan_summary": scan_summary or {},
            },
        )

    def log_document_extract(self, drafts: list[ExtensionDraft]) -> None:
        entries = []
        for idx, draft in enumerate(drafts):
            entries.append({
                "index": idx,
                "di": draft.di,
                "afn": draft.afn,
                "description": draft.description,
                "dir": draft.dir,
                "add": draft.add,
                "fields": list(draft.fields),
                "resp_fields": list(draft.resp_fields),
                "source_excerpt": source_excerpt(draft.source_snapshot) if draft.source_snapshot else {},
                "missing_fields": draft.missing_fields(),
            })
        self.log_stage(
            "document_extract",
            {
                "summary": f"extracted {len(drafts)} message draft(s)",
                "draft_count": len(drafts),
                "drafts": entries,
            },
        )
        extract_path = self.run_dir / "extracted_drafts.json"
        extract_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_draft_inference(
        self,
        draft_index: int,
        draft: ExtensionDraft,
        *,
        inference_report: list[dict[str, Any]],
        field_type_warnings: list[str],
    ) -> None:
        self.log_stage(
            "inference",
            {
                "summary": f"DI={draft.di} inferred {len(inference_report)} field(s)",
                "draft_index": draft_index,
                "di": draft.di,
                "inference_report": inference_report,
                "field_type_warnings": field_type_warnings,
            },
        )

    def log_draft_yaml(
        self,
        draft_index: int,
        draft: ExtensionDraft,
        *,
        yaml_text: str,
        extension_file: str,
    ) -> None:
        yaml_path = self.run_dir / f"draft_{draft_index:03d}_{draft.di}_preview.yaml"
        yaml_path.write_text(yaml_text, encoding="utf-8")
        self.log_stage(
            "yaml_preview",
            {
                "summary": f"DI={draft.di} yaml preview",
                "draft_index": draft_index,
                "di": draft.di,
                "extension_file": extension_file,
                "yaml_path": str(yaml_path),
            },
        )

    def log_draft_fidelity(
        self,
        draft_index: int,
        draft: ExtensionDraft,
        *,
        fidelity_report: dict[str, Any],
    ) -> None:
        self.log_stage(
            "fidelity",
            {
                "summary": (
                    f"DI={draft.di} fidelity "
                    f"{fidelity_report.get('confidence')} "
                    f"score={fidelity_report.get('score')}"
                ),
                "draft_index": draft_index,
                "di": draft.di,
                "fidelity_report": fidelity_report,
            },
        )

    def log_draft_result(
        self,
        draft_index: int,
        draft: ExtensionDraft,
        *,
        status: str,
        error: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "summary": f"DI={draft.di} {status}" + (f": {error}" if error else ""),
            "draft_index": draft_index,
            "di": draft.di,
            "status": status,
            "extension_file": draft.extension_file or None,
            "last_error": error or draft.last_error or None,
        }
        if extra:
            payload.update(extra)
        self.log_stage("draft_result", payload)

    def log_batch_complete(self, summary: dict[str, Any]) -> None:
        self.log_stage(
            "batch_complete",
            {
                "summary": (
                    f"accepted={summary.get('accepted')} "
                    f"failed={summary.get('failed')} "
                    f"total={summary.get('total')}"
                ),
                "batch_summary": summary,
            },
        )
