"""Validate TestPlan build steps against /route input_schema before execution."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from test_runner.error_codes import PLAN_BUILD_SCHEMA_MISMATCH, RunError
from test_runner.variables import VariableError, resolve_value

_LOCATOR_KEYS = frozenset({
    "proto", "func", "afn", "di", "dir", "direction", "intent",
    "address", "preamble", "seq", "addr", "has_address", "add",
})
_BUILD_META_KEYS = frozenset({
    "resolve", "schema", "describe", "set", "from_frame", "from-frame",
    "target", "channel", "scope", "to", "conn", "name",
})
_VAR_REF_RE = re.compile(r"\$\{([^}]+)\}")


@dataclass
class BuildStepRef:
    step_id: str
    args: dict[str, Any]
    section: str = "steps"


@dataclass
class BuildCheckResult:
    step_id: str
    status: str  # ok | mismatch | skipped_dynamic | route_failed | skipped_incomplete_locator
    route_params: dict[str, Any] = field(default_factory=dict)
    input_schema: list[dict[str, Any]] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    type_hints: list[str] = field(default_factory=list)
    message: str = ""
    variant_id: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "step_id": self.step_id,
            "status": self.status,
        }
        if self.route_params:
            out["route_params"] = self.route_params
        if self.input_schema:
            out["input_schema"] = self.input_schema
        if self.unknown_fields:
            out["unknown_fields"] = self.unknown_fields
        if self.missing_required:
            out["missing_required"] = self.missing_required
        if self.type_hints:
            out["type_hints"] = self.type_hints
        if self.message:
            out["message"] = self.message
        if self.variant_id:
            out["variant_id"] = self.variant_id
        if self.path:
            out["path"] = self.path
        return out

    def to_error(self) -> dict[str, Any]:
        parts: list[str] = []
        if self.unknown_fields:
            parts.append(f"unknown_fields: {', '.join(self.unknown_fields)}")
        if self.missing_required:
            parts.append(f"missing_required: {', '.join(self.missing_required)}")
        if self.type_hints:
            parts.append(f"type_hints: {'; '.join(self.type_hints)}")
        message = self.message or "; ".join(parts) or "build args do not match route input_schema"
        return RunError(
            PLAN_BUILD_SCHEMA_MISMATCH,
            message,
            step_id=self.step_id,
            details=self.to_dict(),
        ).to_dict()


def collect_build_steps(plan: dict[str, Any]) -> list[BuildStepRef]:
    refs: list[BuildStepRef] = []
    for section in ("setup", "steps", "teardown"):
        steps = plan.get(section)
        if isinstance(steps, list):
            _walk_steps(steps, section, refs)
    return refs


def check_plan_builds(
    plan: dict[str, Any],
    *,
    vars: dict[str, Any] | None = None,
    resolved_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate all build steps. Use resolved_plan when args were dry-run expanded."""
    scope = {**(plan.get("vars") or {}), **(vars or {})}
    source = resolved_plan or plan
    refs = collect_build_steps(source)
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for ref in refs:
        result = check_build_step(ref.args, scope=scope, step_id=ref.step_id)
        checks.append(result.to_dict())
        if result.status == "mismatch":
            errors.append(result.to_error())
        elif result.status in {"skipped_dynamic", "skipped_incomplete_locator", "route_failed"}:
            warnings.append(result.to_error())

    return {
        "ok": not errors,
        "build_checks": checks,
        "errors": errors or None,
        "warnings": warnings or None,
    }


def check_build_step(
    args: dict[str, Any],
    *,
    scope: dict[str, Any],
    step_id: str = "",
) -> BuildCheckResult:
    resolved_args = _resolve_args(args, scope)
    locator, business = split_locator_and_business(resolved_args)

    if _has_unresolved(locator) or _values_contain_unresolved(business):
        return BuildCheckResult(
            step_id=step_id,
            status="skipped_dynamic",
            route_params=_public_locator(locator),
            message="locator or business args contain unresolved ${...}; resolve vars before strict build check",
        )

    if not locator.get("proto") or not (locator.get("di") or locator.get("func")):
        return BuildCheckResult(
            step_id=step_id,
            status="skipped_incomplete_locator",
            route_params=_public_locator(locator),
            message="incomplete build locator (need proto and di or func)",
        )

    try:
        target = _resolve_target(locator)
    except Exception as exc:
        return BuildCheckResult(
            step_id=step_id,
            status="route_failed",
            route_params=_public_locator(locator),
            message=f"route failed: {exc}",
        )

    schema = target.input_schema
    schema_names = {f.name for f in schema}
    schema_by_name = {f.name: f for f in schema}

    unknown = sorted(k for k in business if k not in schema_names)
    missing = sorted(
        f.name for f in schema
        if f.required and f.name not in business
    )
    type_hints = _type_hints(business, schema_by_name)

    result = BuildCheckResult(
        step_id=step_id,
        status="ok" if not unknown and not missing and not type_hints else "mismatch",
        route_params=_public_locator(locator),
        input_schema=[f.to_dict() for f in schema],
        unknown_fields=unknown,
        missing_required=missing,
        type_hints=type_hints,
        variant_id=target.variant_id,
        path=target.path,
    )
    if result.status == "mismatch":
        result.message = "; ".join(
            part for part in [
                f"unknown_fields: {', '.join(unknown)}" if unknown else "",
                f"missing_required: {', '.join(missing)}" if missing else "",
                "; ".join(type_hints) if type_hints else "",
            ] if part
        )
    return result


def split_locator_and_business(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    locator: dict[str, Any] = {}
    business: dict[str, Any] = {}
    for key, value in args.items():
        if key in _BUILD_META_KEYS:
            continue
        if key in _LOCATOR_KEYS:
            locator[key] = value
        else:
            business[key] = value
    if "direction" in locator and "dir" not in locator:
        locator["dir"] = locator["direction"]
    return locator, business


def build_field_types_catalog() -> list[dict[str, Any]]:
    return [
        {
            "type": "uint8",
            "testplan_shape": "number or numeric string",
            "example": 32,
            "notes": "8-bit unsigned integer field",
        },
        {
            "type": "uint16_le",
            "testplan_shape": "number or numeric string",
            "example": 1024,
            "notes": "little-endian 16-bit unsigned",
        },
        {
            "type": "bcd",
            "testplan_shape": "hex digit string, optional spaces; list for array payload fields",
            "example": "000000000001",
            "notes": "6-byte CSG address uses 12 hex digits; wire byte_order defaults to little",
        },
        {
            "type": "hex",
            "testplan_shape": "hex string",
            "example": "010203",
            "notes": "raw payload bytes as hex",
        },
        {
            "type": "bytes",
            "testplan_shape": "hex string or bytes-like value",
            "example": "AABB",
            "notes": "opaque byte field",
        },
        {
            "type": "ascii",
            "testplan_shape": "string",
            "example": "AB",
            "notes": "fixed-length ASCII string; wire byte_order defaults to little (like bcd/hex)",
        },
        {
            "type": "array",
            "testplan_shape": "JSON/YAML list",
            "example": ["000000000001", "000000000002"],
            "notes": "field name from input_schema (e.g. slave_addrs, nodes); not a single hex blob",
        },
        {
            "type": "struct",
            "testplan_shape": "object/dict or flattened field names per route schema",
            "example": {"address": "000000000001", "device_type": 1},
            "notes": "prefer route input_schema children names",
        },
        {
            "type": "enum",
            "testplan_shape": "string or int matching schema values",
            "example": "downlink",
            "notes": "use values from input_schema.values when present",
        },
    ]


def workflow_catalog() -> dict[str, Any]:
    return {
        "order": [
            "protocol_task_run for each frame (get input_schema)",
            "test.validate (structure + build schema check)",
            "test.dry_run (resolve vars + build schema check on resolved args)",
            "test.run",
        ],
        "rule": "build step field names must match route input_schema; dry_run enforces this before run",
        "on_mismatch": "fix args using returned input_schema / unknown_fields / missing_required",
    }


def _walk_steps(steps: list[Any], section: str, refs: list[BuildStepRef], prefix: str = "") -> None:
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or f"{section}_{index + 1}")
        if prefix:
            step_id = f"{prefix}.{step_id}"
        action = str(step.get("action") or "")
        if action == "build":
            args = step.get("args")
            if isinstance(args, dict):
                refs.append(BuildStepRef(step_id=step_id, args=dict(args), section=section))
        elif action == "loop":
            nested = step.get("steps")
            if isinstance(nested, list):
                _walk_steps(nested, section, refs, prefix=step_id)
        elif action == "if":
            for branch_key in ("steps", "else_steps"):
                nested = step.get(branch_key)
                if isinstance(nested, list):
                    _walk_steps(nested, section, refs, prefix=f"{step_id}.{branch_key}")


def _resolve_args(args: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    try:
        resolved = resolve_value(deepcopy(args), scope)
    except VariableError:
        resolved = deepcopy(args)
    return resolved if isinstance(resolved, dict) else {}


def _resolve_target(locator: dict[str, Any]) -> Any:
    from console.build_resolver import resolve

    target_info = dict(locator)
    if "proto" in target_info:
        target_info["proto"] = _normalize_proto(str(target_info["proto"]))
    return resolve(target_info)


def _normalize_proto(name: str) -> str:
    mapping = {"dlt645": "dlt645_2007", "csg": "csg_2016"}
    return mapping.get(name, name)


def _public_locator(locator: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("proto", "func", "afn", "di", "dir", "direction"):
        if key in locator and locator[key] not in (None, ""):
            out[key] = locator[key]
    return out


def _has_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, dict):
        return any(_has_unresolved(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_unresolved(v) for v in value)
    return False


def _values_contain_unresolved(value: Any) -> bool:
    return _has_unresolved(value)


def _type_hints(business: dict[str, Any], schema_by_name: dict[str, Any]) -> list[str]:
    from console.build_resolver import InputField
    from console.schema_validate import validate_business_values

    schema = [
        field for field in schema_by_name.values()
        if isinstance(field, InputField)
    ]
    return validate_business_values(business, schema)
