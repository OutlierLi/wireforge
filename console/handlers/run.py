"""/run 命令处理器 — execute a YAML TestPlan."""

from __future__ import annotations

from typing import Any

from console.response import ok, fail, missing_param
from console.runner.plan import PlanError
from console.runner.runner import run_test_plan


def handle(args: dict[str, Any]) -> dict:
    file = args.get("file") or args.get("path")
    if not file:
        return missing_param("file", "str", examples=["tests/sta_join.yaml"])
    try:
        data = run_test_plan(
            str(file),
            cli_vars=_parse_cli_vars(args.get("var")),
            dry_run=_as_bool(args.get("dry_run", args.get("dry-run", False))),
            timeout_ms=_optional_int(args.get("timeout")),
            report=str(args["report"]) if args.get("report") else None,
        )
        if isinstance(data, dict) and isinstance(data.get("_legacy"), dict):
            data = data["_legacy"]
    except PlanError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"run failed: {exc}")
    return ok(data)


def _parse_cli_vars(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    items = raw if isinstance(raw, list) else [raw]
    parsed: dict[str, Any] = {}
    for item in items:
        text = str(item)
        if "=" not in text:
            raise PlanError(f"--var must be key=value, got: {text}")
        key, value = text.split("=", 1)
        parsed[key.strip()] = value
    return parsed


def _optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    return int(raw)


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
