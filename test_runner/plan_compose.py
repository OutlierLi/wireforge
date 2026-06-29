"""Compose-time plan expansion — include fragments and parametrize into flat steps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from test_runner.conditions import evaluate_when
from test_runner.plan_loader import PlanError
from test_runner.variables import VariableError, resolve_value

ROOT = Path(__file__).resolve().parent.parent

COMPOSE_ACTIONS = frozenset({"include", "parametrize"})


def compose_plan(
    plan: dict[str, Any],
    *,
    plan_path: Path | str | None = None,
    vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expand include/parametrize steps; strip compose-only metadata."""
    out = deepcopy(plan)
    base = Path(plan_path) if plan_path else None
    scope = {**(out.get("vars") or {}), **(vars or {})}

    for section in ("setup", "steps", "teardown"):
        items = out.get(section)
        if isinstance(items, list):
            out[section] = compose_steps(items, scope=scope, plan_path=base)

    out.pop("fragments", None)
    return out


def compose_steps(
    steps: list[Any],
    *,
    scope: dict[str, Any],
    plan_path: Path | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        if action == "include":
            out.extend(_expand_include(step, scope=scope, plan_path=plan_path))
            continue
        if action == "parametrize":
            out.extend(_expand_parametrize(step, scope=scope, plan_path=plan_path))
            continue
        if action in {"loop", "if"}:
            cloned = deepcopy(step)
            nested = cloned.get("steps")
            if isinstance(nested, list):
                cloned["steps"] = compose_steps(nested, scope=scope, plan_path=plan_path)
            else_steps = cloned.get("else_steps")
            if isinstance(else_steps, list):
                cloned["else_steps"] = compose_steps(else_steps, scope=scope, plan_path=plan_path)
            out.append(cloned)
            continue
        out.append(deepcopy(step))
    return out


def _expand_include(
    step: dict[str, Any],
    *,
    scope: dict[str, Any],
    plan_path: Path | None,
) -> list[dict[str, Any]]:
    args = dict(step.get("args") or {})
    when = args.get("when")
    if when is not None and not evaluate_when(when, scope):
        return []

    file_ref = args.get("file") or args.get("path")
    if not file_ref:
        step_id = step.get("id") or "include"
        raise PlanError(f"{step_id}: include requires args.file")

    fragment_path = _resolve_fragment_path(str(file_ref), plan_path)
    if not fragment_path.exists():
        raise PlanError(f"include fragment not found: {fragment_path}")

    try:
        fragment = yaml.safe_load(fragment_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PlanError(f"failed to load include {fragment_path}: {exc}") from exc

    fragment_vars = dict(args.get("vars") or {})
    if fragment_vars:
        try:
            fragment_vars = resolve_value(fragment_vars, scope)
        except VariableError as exc:
            raise PlanError(f"include vars unresolved: {exc}") from exc

    frag_scope = {**scope, **fragment_vars}
    section = str(args.get("section") or "steps")
    frag_steps = _fragment_steps(fragment, section)
    return compose_steps(frag_steps, scope=frag_scope, plan_path=fragment_path.parent)


def _expand_parametrize(
    step: dict[str, Any],
    *,
    scope: dict[str, Any],
    plan_path: Path | None,
) -> list[dict[str, Any]]:
    step_id = str(step.get("id") or "parametrize")
    args = dict(step.get("args") or {})
    nested = step.get("steps") or []
    if not isinstance(nested, list) or not nested:
        raise PlanError(f"{step_id}: parametrize requires non-empty steps")

    item_var = str(args.get("as") or args.get("item_as") or "item")
    index_var = args.get("index_as") or args.get("index_var")
    iterations = _resolve_iterations(args, scope, step_id)

    expanded: list[dict[str, Any]] = []
    for iter_index, (idx, item) in enumerate(iterations):
        prefix = f"{step_id}_{iter_index}"
        iter_scope = dict(scope)
        if item is not None:
            iter_scope[item_var] = item
            expanded.append(
                {
                    "id": f"{prefix}.__bind_{item_var}",
                    "action": "set_var",
                    "args": {"name": item_var, "value": item},
                }
            )
        if index_var:
            iter_scope[str(index_var)] = idx
            expanded.append(
                {
                    "id": f"{prefix}.__bind_{index_var}",
                    "action": "set_var",
                    "args": {"name": str(index_var), "value": idx},
                }
            )
        elif args.get("count") is not None:
            iter_scope["i"] = idx
            expanded.append(
                {
                    "id": f"{prefix}.__bind_i",
                    "action": "set_var",
                    "args": {"name": "i", "value": idx},
                }
            )

        for child in nested:
            action = str(child.get("action") or "")
            if action == "include":
                frag_steps = _expand_include(child, scope=iter_scope, plan_path=plan_path)
                for frag_step in frag_steps:
                    cloned = deepcopy(frag_step)
                    child_id = str(cloned.get("id") or "step")
                    cloned["id"] = f"{prefix}.{child_id}"
                    expanded.append(cloned)
                continue
            cloned = deepcopy(child)
            child_id = str(cloned.get("id") or "step")
            cloned["id"] = f"{prefix}.{child_id}"
            expanded.append(cloned)

    return expanded


def _resolve_iterations(
    args: dict[str, Any],
    scope: dict[str, Any],
    step_id: str,
) -> list[tuple[int, Any | None]]:
    try:
        if "over" in args:
            over = resolve_value(args["over"], scope)
            if isinstance(over, str):
                over = resolve_value("${" + over + "}", scope)
            if not isinstance(over, list):
                raise PlanError(f"{step_id}: parametrize.over must resolve to a list")
            return [(i, item) for i, item in enumerate(over)]

        if "count" in args:
            count = int(resolve_value(args["count"], scope))
            start = int(resolve_value(args.get("start", 0), scope))
            return [(start + i, None) for i in range(count)]
    except PlanError:
        raise
    except (VariableError, TypeError, ValueError) as exc:
        raise PlanError(f"{step_id}: parametrize args unresolved: {exc}") from exc

    raise PlanError(f"{step_id}: parametrize requires args.over or args.count")


def _fragment_steps(fragment: Any, section: str) -> list[dict[str, Any]]:
    if isinstance(fragment, list):
        return fragment
    if not isinstance(fragment, dict):
        raise PlanError("include fragment must be a YAML object or step list")
    steps = fragment.get(section)
    if isinstance(steps, list):
        return steps
    if section == "steps" and any(k in fragment for k in ("setup", "teardown")):
        raise PlanError(f"include fragment section {section!r} missing or not a list")
    raise PlanError(f"include fragment section {section!r} missing or not a list")


def _resolve_fragment_path(file_ref: str, plan_path: Path | None) -> Path:
    path = Path(file_ref)
    if path.is_absolute():
        return path
    if plan_path is not None:
        candidate = (plan_path.parent / path).resolve()
        if candidate.exists():
            return candidate
    return (ROOT / path).resolve()
