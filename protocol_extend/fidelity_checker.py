"""Compare final extension spec/YAML against frozen source snapshot."""

from __future__ import annotations

import re
from typing import Any

from protocol_extend import evidence_parser as ep
from protocol_extend.fields import field_to_yaml
from protocol_extend.schema import ExtensionSpec
from protocol_extend.source_snapshot import normalize_description, source_excerpt

_VALUE_TABLE_IN_TEXT = re.compile(r"(?:0x)?[0-9A-Fa-f]{1,4}H?\s*[：:\-—]|^\d+\s*[：:\-—]", re.I | re.M)


def _confidence_from_score(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _yaml_fields(spec: ExtensionSpec) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    down = [field_to_yaml(f) for f in (spec.fields or [])]
    up = [field_to_yaml(f) for f in (spec.resp_fields or spec.fields or [])]
    if spec.pair and spec.resp_fields:
        up = [field_to_yaml(f) for f in spec.resp_fields]
    elif not spec.pair:
        up = []
    return down, up


def _field_names(fields: list[dict[str, Any]]) -> set[str]:
    return {str(f.get("name") or "").strip().lower() for f in fields if f.get("name")}


def _snapshot_field_names(snapshot: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for row in snapshot.get("field_rows") or []:
        name = str(row.get("name") or "").strip().lower()
        if name:
            names.add(name)
    for f in snapshot.get("fields") or []:
        name = str(f.get("name") or "").strip().lower()
        if name:
            names.add(name)
    return names


def _description_match(expected: str, actual: str) -> bool:
    exp = normalize_description(expected)
    act = normalize_description(actual)
    if not exp or not act:
        return bool(exp) == bool(act)
    return exp in act or act in exp or exp == act


def _source_has_value_table(field_row: dict[str, Any]) -> bool:
    texts = list(field_row.get("evidence") or [])
    if field_row.get("desc"):
        texts.append(str(field_row["desc"]))
    if field_row.get("raw_row"):
        texts.append(" ".join(str(c) for c in field_row["raw_row"]))
    blob = "\n".join(texts)
    if ep.parse_value_table(texts):
        return True
    return bool(_VALUE_TABLE_IN_TEXT.search(blob))


def _yaml_field_length(yaml_field: dict[str, Any]) -> int | None:
    if yaml_field.get("length") is not None:
        try:
            return int(yaml_field["length"])
        except (TypeError, ValueError):
            pass
    ftype = str(yaml_field.get("type") or "")
    if ftype in ("uint8",):
        return 1
    if ftype in ("uint16_le", "uint16_be"):
        return 2
    return None


def fidelity_preview(report: dict[str, Any]) -> dict[str, Any]:
    failed = [c for c in report.get("checks") or [] if not c.get("ok")]
    return {
        "confidence": report.get("confidence"),
        "score": report.get("score"),
        "summary": report.get("summary"),
        "failed_checks": [
            {k: v for k, v in c.items() if k in ("id", "expected", "actual", "missing", "extra", "issues")}
            for c in failed
        ],
    }


def accept_allowed(report: dict[str, Any], *, force: bool = False) -> bool:
    if force:
        return True
    return report.get("confidence") == "high"


def check_fidelity(
    snapshot: dict[str, Any],
    spec: ExtensionSpec,
    inference_report: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return fidelity report with score and confidence vs frozen source."""
    inference_report = inference_report or []
    if not snapshot:
        return {
            "confidence": "medium",
            "score": 50,
            "checks": [{"id": "snapshot_missing", "ok": False, "weight": 0}],
            "summary": "无原始来源快照，无法完整校验",
            "source_excerpt": {},
        }

    checks: list[dict[str, Any]] = []
    earned = 0
    total_weight = 0
    manual = snapshot.get("source") == "manual"
    has_field_table = bool(snapshot.get("field_rows"))

    # DI
    w = 15
    total_weight += w
    di_ok = (snapshot.get("di") or "").upper() == (spec.di or "").upper()
    if di_ok:
        earned += w
    checks.append({"id": "di_match", "ok": di_ok, "weight": w, "expected": snapshot.get("di"), "actual": spec.di})

    # AFN
    w = 10
    total_weight += w
    snap_afn = snapshot.get("afn")
    afn_ok = snap_afn is None or spec.afn is None or int(snap_afn) == int(spec.afn)
    if afn_ok:
        earned += w
    checks.append({"id": "afn_match", "ok": afn_ok, "weight": w, "expected": snap_afn, "actual": spec.afn})

    # Description
    w = 10
    total_weight += w
    exp_desc = snapshot.get("description") or snapshot.get("title") or ""
    act_desc = spec.description or ""
    desc_ok = _description_match(exp_desc, act_desc)
    if desc_ok:
        earned += w
    checks.append({
        "id": "description_match",
        "ok": desc_ok,
        "weight": w,
        "expected": exp_desc,
        "actual": act_desc,
    })

    # Direction (only when snapshot has hint)
    dir_hint = snapshot.get("dir_hint")
    if dir_hint is not None and spec.afn_uses_dir():
        w = 15
        total_weight += w
        dir_ok = int(dir_hint) == int(spec.dir if spec.dir is not None else -1)
        if dir_ok:
            earned += w
        checks.append({
            "id": "dir_match",
            "ok": dir_ok,
            "weight": w,
            "expected": "uplink" if dir_hint == 1 else "downlink",
            "actual": "uplink" if spec.dir == 1 else "downlink",
        })

    yaml_down, yaml_up = _yaml_fields(spec)
    snap_count = len(snapshot.get("field_rows") or snapshot.get("fields") or [])

    # Field count — compare downlink body to snapshot fields when not pair
    if has_field_table:
        w = 20
        total_weight += w
        expected_count = snap_count
        actual_count = len(yaml_down) if not spec.pair else len(yaml_down)
        count_ok = expected_count == actual_count
        if count_ok:
            earned += w
        elif abs(expected_count - actual_count) == 1:
            earned += w // 2
        checks.append({
            "id": "field_count",
            "ok": count_ok,
            "weight": w,
            "expected": expected_count,
            "actual": actual_count,
        })

    # Field names
    if has_field_table:
        w = 15
        total_weight += w
        snap_names = _snapshot_field_names(snapshot)
        yaml_names = _field_names(yaml_down)
        missing = sorted(snap_names - yaml_names)
        extra = sorted(yaml_names - snap_names)
        names_ok = not missing and not extra
        if names_ok:
            earned += w
        elif not missing:
            earned += w // 2
        checks.append({
            "id": "field_names",
            "ok": names_ok,
            "weight": w,
            "missing": missing,
            "extra": extra,
        })

    # Field types / evidence
    if has_field_table:
        w = 25
        total_weight += w
        issues: list[str] = []
        yaml_by_name = {str(f.get("name", "")).lower(): f for f in yaml_down}
        for row in snapshot.get("field_rows") or []:
            name = str(row.get("name") or "").lower()
            if not name:
                continue
            yf = yaml_by_name.get(name)
            if not yf:
                continue
            if _source_has_value_table(row):
                ytype = str(yf.get("type") or "")
                if ytype not in ("enum",):
                    issues.append(f"{name}: source has value table but yaml type is {ytype}")
            snap_bytes = row.get("bytes")
            ylen = _yaml_field_length(yf)
            if snap_bytes is not None and ylen is not None and int(snap_bytes) != int(ylen):
                issues.append(f"{name}: byte length {ylen} != source {snap_bytes}")
        types_ok = not issues
        if types_ok:
            earned += w
        elif len(issues) <= 1:
            earned += w // 2
        checks.append({"id": "field_types", "ok": types_ok, "weight": w, "issues": issues})

    # Unknown inference penalties
    unknowns = [e for e in inference_report if e.get("semantic_type") == "unknown"]
    if unknowns:
        w = 10
        total_weight += w
        checks.append({
            "id": "inference_unknown",
            "ok": False,
            "weight": w,
            "issues": [e.get("name") for e in unknowns],
        })
    else:
        w = 10
        total_weight += w
        earned += w
        checks.append({"id": "inference_unknown", "ok": True, "weight": w})

    score = int(round(100 * earned / total_weight)) if total_weight else 0
    confidence = _confidence_from_score(score)

    for critical_id in ("description_match", "dir_match", "field_count"):
        critical = next((c for c in checks if c["id"] == critical_id), None)
        if critical and not critical.get("ok"):
            if confidence == "high":
                confidence = "medium"
                score = min(score, 79)

    types_check = next((c for c in checks if c["id"] == "field_types"), None)
    if types_check and not types_check.get("ok") and types_check.get("issues"):
        confidence = "medium" if confidence == "high" else confidence
        score = min(score, 79) if confidence == "medium" else score

    if manual and not has_field_table and (spec.fields or spec.resp_fields) and confidence == "high":
        confidence = "medium"
        score = min(score, 79)

    failed = [c["id"] for c in checks if not c.get("ok")]
    if not failed:
        summary = "与原始来源一致"
    else:
        summary = f"与原始来源不一致: {', '.join(failed)}"

    report = {
        "confidence": confidence,
        "score": score,
        "checks": checks,
        "summary": summary,
        "source_excerpt": source_excerpt(snapshot),
    }
    return report


def _yaml_field_issues(fields: list[dict[str, Any]], *, prefix: str = "fields") -> list[str]:
    issues: list[str] = []
    names: list[str] = []

    for idx, field in enumerate(fields):
        name = str(field.get("name") or "").strip()
        path = f"{prefix}[{idx}]"
        if not name:
            issues.append(f"{path}.name missing")
            continue
        names.append(name)

        if field.get("type") == "array":
            count_ref = str(field.get("count_ref") or "").strip()
            if not count_ref:
                issues.append(f"{path}.count_ref missing")
            elif count_ref not in names:
                issues.append(f"{path}.count_ref '{count_ref}' not found in prior fields")
            item_type = field.get("item_type")
            if not item_type:
                issues.append(f"{path}.item_type missing")

        for scalar_type in ("hex", "bytes"):
            if field.get("type") == scalar_type and field.get("length_from"):
                ref = str(field.get("length_from") or "").strip()
                if ref and ref not in names:
                    issues.append(f"{path}.length_from '{ref}' not found in prior fields")

        if field.get("type") == "enum":
            values = field.get("values") or {}
            if len(values) < 2:
                issues.append(f"{path}.enum needs >=2 values")

        nested = field.get("fields")
        if field.get("type") == "struct" and isinstance(nested, list):
            issues.extend(_yaml_field_issues(nested, prefix=f"{path}.fields"))

    return issues


def check_layout_fidelity(spec: ExtensionSpec) -> dict[str, Any]:
    """Layout-only fidelity for C struct pipeline (no DOCX snapshot)."""
    checks: list[dict[str, Any]] = []
    earned = 0
    total_weight = 0

    def add_check(check_id: str, ok: bool, weight: int, **extra: Any) -> None:
        nonlocal earned, total_weight
        total_weight += weight
        if ok:
            earned += weight
        checks.append({"id": check_id, "ok": ok, "weight": weight, **extra})

    add_check("di_present", bool(spec.di), 15, expected=spec.di)
    if spec.protocol == "dlt645_2007":
        add_check("func_present", spec.func is not None, 10, expected=spec.func)
    else:
        add_check("afn_present", spec.afn is not None, 10, expected=spec.afn)
    add_check("description_present", bool(spec.description), 10)

    field_issues = _yaml_field_issues(spec.fields or [])
    if spec.resp_fields:
        field_issues.extend(_yaml_field_issues(spec.resp_fields, prefix="resp_fields"))
    add_check("field_layout", not field_issues, 40, issues=field_issues)

    has_payload = bool(spec.fields or spec.resp_fields)
    add_check("payload_defined", True, 25, empty=not has_payload)

    score = int(round(100 * earned / total_weight)) if total_weight else 0
    confidence = _confidence_from_score(score)
    failed = [c["id"] for c in checks if not c.get("ok")]
    summary = "layout ok" if not failed else f"layout issues: {', '.join(failed)}"

    return {
        "confidence": confidence,
        "score": score,
        "checks": checks,
        "summary": summary,
        "source": "c_struct_layout",
    }
