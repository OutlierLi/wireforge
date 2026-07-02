from __future__ import annotations

import json
import time
import traceback
from copy import deepcopy
from typing import Any

from runtime.command_runtime import execute as runtime_execute
from test_runner.context import RunContext, StepRecord
from test_runner.conditions import values_equal
from test_runner.expressions import eval_expression
from test_runner.lab_context import LabError
from test_runner.variables import VariableError, resolve_value


class StepFailed(RuntimeError):
    def __init__(self, step_id: str, action: str, result: dict[str, Any]):
        self.step_id = step_id
        self.action = action
        self.result = result
        super().__init__(result.get("error") or result.get("status") or "step failed")


_SERIAL_MGMT_ACTIONS = frozenset({
    "serial.connect",
    "serial.open",
    "serial.close",
    "serial.set",
    "serial.disconnect",
})


class StepExecutor:
    def execute(self, step: dict[str, Any], ctx: RunContext) -> StepRecord:
        step_id = str(step["id"])
        action = str(step["action"])
        start = time.monotonic()
        try:
            result = self._execute(step, ctx)
            elapsed = int((time.monotonic() - start) * 1000)
            record = StepRecord(step_id, action, "ok", elapsed, result=result)
            self._store_step_result(step, ctx, result)
            return record
        except StepFailed as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return StepRecord(step_id, action, "fail", elapsed, str(exc), result=exc.result)
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return StepRecord(step_id, action, "fail", elapsed, str(exc), result={"error": str(exc)})

    def resolve_step(
        self,
        step: dict[str, Any],
        ctx: RunContext | Any,
        *,
        soft: bool = False,
    ) -> dict[str, Any]:
        resolved = deepcopy(step)
        action = str(resolved.get("action", ""))
        if "args" in resolved:
            if soft:
                resolved["args"] = resolve_value(resolved["args"], self._scope(ctx), soft=True)
            else:
                resolved["args"] = resolve_value(resolved["args"], self._scope(ctx))
            if action not in {"loop", "if", "expr", "set_var", "assert"}:
                try:
                    translated, lab_meta = self._apply_lab_context(action, dict(resolved["args"] or {}), ctx)
                    _, resolved["args"] = self._to_command(action, translated)
                    if lab_meta:
                        resolved["_lab"] = lab_meta
                except VariableError:
                    if not soft:
                        raise
                except LabError:
                    if not soft:
                        raise
        nested = resolved.get("steps")
        child_soft = soft or action == "if"
        if action == "loop" and isinstance(nested, list):
            # Body steps run in per-iteration scope; do not resolve with outer vars here.
            resolved["steps"] = [deepcopy(child) for child in nested]
        elif action == "if" and isinstance(nested, list):
            resolved["steps"] = [self.resolve_step(child, ctx, soft=child_soft) for child in nested]
        else_steps = resolved.get("else_steps")
        if action == "if" and isinstance(else_steps, list):
            resolved["else_steps"] = [self.resolve_step(child, ctx, soft=True) for child in else_steps]
        return resolved

    def _execute(self, step: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
        resolved = self.resolve_step(step, ctx)
        action = str(resolved["action"])
        args = dict(resolved.get("args") or {})
        lab_meta: dict[str, Any] | None = resolved.get("_lab") if isinstance(resolved.get("_lab"), dict) else None

        if ctx.dry_run:
            data: dict[str, Any] = {"dry_run": True, "action": action, "args": args}
            if lab_meta:
                data["_lab"] = lab_meta
            return {"schema": "protocol-tui.v1", "status": "success", "data": data}

        if action == "sleep":
            ms = int(args.get("ms") or args.get("timeout_ms") or args.get("value") or 0)
            if not ms and args.get("seconds") is not None:
                ms = int(float(args["seconds"]) * 1000)
            time.sleep(ms / 1000.0)
            return {"schema": "protocol-tui.v1", "status": "success", "data": {"elapsed_ms": ms}}

        if action == "set_var":
            name = args.get("name")
            if not name:
                return self._failure("set_var requires args.name")
            ctx.vars[str(name)] = args.get("value")
            return {"schema": "protocol-tui.v1", "status": "success", "data": {"name": str(name), "value": args.get("value")}}

        if action == "expr":
            name = args.get("name")
            expr = args.get("expr")
            if not name or expr is None or expr == "":
                return self._failure("expr requires args.name and args.expr")
            try:
                value = eval_expression(str(expr), self._scope(ctx))
            except Exception as exc:
                return self._failure(f"expr failed: {exc}")
            ctx.vars[str(name)] = value
            return {"schema": "protocol-tui.v1", "status": "success", "data": {"name": str(name), "value": value, "expr": str(expr)}}

        if action == "assert":
            result = self._assert(args, ctx)
            if result.get("status") != "success":
                raise StepFailed(str(step["id"]), action, result)
            return result

        if not lab_meta:
            args, lab_meta = self._apply_lab_context(action, args, ctx)

        if action == "wait_log":
            result = self._wait_log(args)
            if lab_meta:
                self._attach_lab_meta(result, lab_meta)
            if result.get("status") != "success":
                raise StepFailed(str(step["id"]), action, result)
            return result

        command, command_args = self._to_command(action, args)
        if action == "request":
            command_args = self._prepare_request_args(command_args)

        result = runtime_execute(command, command_args)
        if lab_meta:
            self._attach_lab_meta(result, lab_meta)
        if result.get("status") != "success":
            raise StepFailed(str(step["id"]), action, result)
        return result

    def _to_command(self, action: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        args = self._normalize_common_args(args, action=action)
        if action.startswith("serial."):
            sub = action.split(".", 1)[1]
            if sub == "disconnect":
                sub = "disconnect"
            return "serial", {**args, "sub": sub}
        if action == "send":
            return "serial", {**args, "sub": "send"}
        if action in {"wait_frame", "wait-frame"}:
            return "wait-frame", self._flatten_expect(args, prefix="expect")
        if action == "request":
            return "request", args
        if action.startswith("auto_rule."):
            sub = action.split(".", 1)[1]
            if sub == "remove":
                sub = "delete"
            return "auto_rule", {**args, "sub": sub}
        if action in {"build", "decode"}:
            return action, args
        return action, args

    def _prepare_request_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args)
        build = args.pop("build", None)
        wait = args.pop("wait", None)
        if build is not None:
            if not isinstance(build, dict):
                raise StepFailed("", "request", self._failure("request.build must be an object"))
            build_args = build.get("args")
            if build_args is None:
                build_args = {k: v for k, v in build.items() if k not in {"intent", "payload"}}
            if not build_args:
                raise StepFailed("", "request", self._failure("request.build requires explicit build args in v1"))
            build_result = runtime_execute("build", dict(build_args))
            if build_result.get("status") != "success":
                raise StepFailed("", "request", build_result)
            frame = (build_result.get("data") or {}).get("frame")
            if not frame:
                raise StepFailed("", "request", self._failure("build did not return frame"))
            args["send"] = frame
        if wait is not None:
            if not isinstance(wait, dict):
                raise StepFailed("", "request", self._failure("request.wait must be an object"))
            if "timeout_ms" in wait and "timeout" not in args:
                args["timeout"] = wait["timeout_ms"]
            expect = wait.get("expect")
            if isinstance(expect, dict):
                args.update(self._flatten_mapping(expect, "wait"))
            for k, v in wait.items():
                if k not in {"timeout_ms", "expect"}:
                    args[f"wait.{k}"] = v
        return self._normalize_common_args(args, action="request")

    def _normalize_common_args(self, args: dict[str, Any], action: str = "") -> dict[str, Any]:
        out = dict(args)
        if "conn" in out:
            if action in _SERIAL_MGMT_ACTIONS:
                if "name" not in out:
                    out["name"] = out.pop("conn")
                else:
                    out.pop("conn", None)
            elif "to" not in out:
                out["to"] = out.pop("conn")
            else:
                out.pop("conn", None)
        if "timeout_ms" in out and "timeout" not in out:
            out["timeout"] = out.pop("timeout_ms")
        if "frame_hex" in out and "hex" not in out:
            out["hex"] = out["frame_hex"]
        return out

    def _apply_lab_context(
        self,
        action: str,
        args: dict[str, Any],
        ctx: RunContext | Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        lab = getattr(ctx, "lab", None)
        if lab is None:
            return args, None
        return lab.translate_args(action, args)

    def _wait_log(self, args: dict[str, Any]) -> dict[str, Any]:
        from lab_service import get_lab_service

        lab = get_lab_service()
        args = lab.normalize_args(args)
        target = lab.connection_id(args) or "default"
        timeout_ms = int(args.get("timeout") or args.get("timeout_ms") or 5000)
        expect = args.get("expect") if isinstance(args.get("expect"), dict) else {}
        contains = str(expect.get("contains") or args.get("contains") or "")
        if not contains:
            return self._failure("wait_log requires expect.contains")
        transport = lab.get_connection(target)
        if not transport:
            return self._failure(
                f"serial not connected (to={target}). use /serial connect --name {target} --port <port> first"
            )

        deadline = time.monotonic() + timeout_ms / 1000.0
        chunks: list[str] = []
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            data = transport.read_response(min(0.2, remaining))
            if data:
                text = data.decode("utf-8", errors="replace")
                chunks.append(text)
                joined = "".join(chunks)
                if contains in joined:
                    return {
                        "schema": "protocol-tui.v1",
                        "status": "success",
                        "data": {
                            "matched": True,
                            "contains": contains,
                            "text": joined,
                            "debug_line": joined,
                        },
                    }
            time.sleep(0.02)
        return self._failure(
            "timeout: no debug log matched expect conditions",
            {"timeout_ms": timeout_ms, "contains": contains, "text": "".join(chunks)},
        )

    def _flatten_expect(self, args: dict[str, Any], prefix: str) -> dict[str, Any]:
        out = dict(args)
        expect = out.pop("expect", None)
        if isinstance(expect, dict):
            out.update(self._flatten_mapping(expect, prefix))
        return self._normalize_common_args(out)

    def _flatten_mapping(self, mapping: dict[str, Any], prefix: str) -> dict[str, Any]:
        return {f"{prefix}.{k}": v for k, v in _flatten_dict(mapping).items()}

    def _assert(self, args: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
        scope = self._scope(ctx)
        conditions = args.get("expect") if isinstance(args.get("expect"), dict) else args
        failures = []
        for path, expected in conditions.items():
            if path in {"op"}:
                continue
            try:
                actual = resolve_value("${" + path + "}", scope)
            except Exception:
                actual = None
            if not values_equal(actual, expected):
                failures.append({"path": path, "expected": expected, "actual": actual})
        if failures:
            return self._failure("assert failed", {"failures": failures})
        return {"schema": "protocol-tui.v1", "status": "success", "data": {"asserted": len(conditions)}}

    def _store_step_result(self, step: dict[str, Any], ctx: RunContext, result: dict[str, Any]) -> None:
        data = result.get("data", {})
        stored = _augment_data_aliases(data)
        ctx.step_results[str(step["id"])] = stored
        ctx.vars[str(step["id"])] = stored
        save_as = step.get("save_as")
        if save_as:
            ctx.vars[str(save_as)] = stored

    def _scope(self, ctx: RunContext | Any) -> dict[str, Any]:
        scope = dict(getattr(ctx, "vars", {}))
        step_results = getattr(ctx, "step_results", {})
        scope.update(step_results)
        return scope

    @staticmethod
    def _failure(error: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {"schema": "protocol-tui.v1", "status": "execution_error", "error": error}
        if detail:
            result["detail"] = detail
        return result

    @staticmethod
    def _attach_lab_meta(result: dict[str, Any], lab_meta: dict[str, Any]) -> None:
        data = result.setdefault("data", {})
        if isinstance(data, dict):
            data["_lab"] = lab_meta


def _flatten_dict(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            out.update(_flatten_dict(child, path))
        else:
            out[path] = child
    return out


def _augment_data_aliases(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = deepcopy(data)
    if "frame" in out and "frame_hex" not in out:
        out["frame_hex"] = out["frame"]
    return out
