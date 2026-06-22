"""命令处理器 — 对接 protocol_tool API。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from console.command import registry, Command, Param

ROOT = Path(__file__).resolve().parent.parent  # wireforge/


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class CmdResult:
    """命令执行结果。包含结构化 WireForgeResult 和扁平兼容字段。"""
    success: bool
    command: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    path: str = ""
    frame_hex: str = ""
    # 结构化结果 (wireforge.result/v1)
    structured: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        if self.structured:
            return self.structured
        d: dict[str, Any] = {"success": self.success, "command": self.command}
        if self.output: d["output"] = self.output
        if self.error:  d["error"] = self.error
        if self.path:   d["path"] = self.path
        if self.frame_hex: d["frame"] = self.frame_hex
        return d


# ── Helpers ───────────────────────────────────────────────────────────

def _proto(name: str) -> str:
    m = {"dlt645": "dlt645_2007", "dlt645_2007": "dlt645_2007",
         "csg": "csg_2016", "csg_2016": "csg_2016"}
    return m.get(name, name)


def _ensure_ir(proto: str):
    ip = ROOT / "compiled" / f"{proto}.ir.json"
    if not ip.exists():
        from protocol_tool.compiler.pipeline import compile_protocol
        reg = ROOT / "protocol_tool" / "protocols" / "registry.yaml"
        compile_protocol(str(reg), proto, output_dir=str(ROOT / "compiled"))


def _hex(v: Any) -> int:
    """将 hex 字符串或 int 转为 int。"""
    if isinstance(v, int): return v
    s = str(v).replace("0x", "").replace("0X", "")
    return int(s, 16)


# ── Build ─────────────────────────────────────────────────────────────

def handle_build(args: dict[str, Any]) -> CmdResult:
    """两阶段 Build: Resolve → Encode。

    Phase 1: /build --proto csg --di E8020701 --resolve
             → 返回 input_schema

    Phase 2: /build --proto csg --di E8020701 --voltage 220 --current 5
             → 构造完整帧
    """
    from console.build_resolver import resolve, encode, BuildTarget

    # 如果只传了定位参数没有业务字段，返回 input_schema
    resolve_only = args.get("resolve", False) or args.get("schema", False)
    # 区分定位参数和业务参数
    target_keys = {"proto", "func", "afn", "di", "dir", "address", "intent",
                   "preamble", "seq", "addr", "direction", "has_address", "resolve", "schema"}
    target_info = {k: v for k, v in args.items() if k in target_keys and v is not None}
    business_values = {k: v for k, v in args.items() if k not in target_keys}

    try:
        target = resolve(target_info)
    except Exception as e:
        return CmdResult(success=False, command="build", error=str(e))

    # --resolve: 只返回 input_schema，不构造帧
    if resolve_only:
        return CmdResult(
            success=True, command="build",
            path=target.path,
            output=target.to_dict(),
        )

    # 将定位参数中同时作为业务字段的值 (如 di) 合并到 business_values
    schema_names = {f.name for f in target.input_schema}
    for k, v in target_info.items():
        if k in schema_names and k not in business_values:
            business_values[k] = v

    # 正常构造: 如果 schema 为空（无必填业务字段），直接编码
    has_required = any(f.required for f in target.input_schema)
    if not business_values and has_required:
        return CmdResult(
            success=False, command="build",
            error="no business fields provided. "
                  "Use --resolve to see input_schema, then provide required fields",
            path=target.path,
            output={"input_schema": [f.to_dict() for f in target.input_schema],
                    "derived_fields": target.derived_fields},
        )

    try:
        frame_hex = encode(target, business_values)
        structured = {
            "schema_version": "wireforge.result/v1",
            "operation": "build",
            "status": "ok",
            "protocol": {"id": target.protocol},
            "resolved": {
                "message_id": target.message_id,
                "variant_id": target.variant_id,
            },
            "frame": {},
            "payload": {},
            "wire": {"hex": frame_hex, "fields": []},
            "diagnostics": {"checks": [], "warnings": [], "errors": []},
        }
        return CmdResult(
            success=True, command="build",
            path=target.path, frame_hex=frame_hex,
            structured=structured,
        )
    except Exception as e:
        err = str(e)
        # 提取缺失字段名
        missing = ""
        if "Required field" in err and "not provided" in err:
            import re
            m = re.search(r"Required field '(\w+)' not provided", err)
            if m:
                missing = m.group(1)

        schema_info = [f.to_dict() for f in target.input_schema]
        hint = ""
        if missing:
            required_names = [f.name for f in target.input_schema if f.required]
            hint = (f"missing required field: '{missing}'. "
                    f"All required: {required_names}. "
                    f"Use --resolve to see full input_schema")
        elif schema_info:
            hint = (f"build failed: {err}. "
                    f"Use --resolve to see input_schema")

        return CmdResult(
            success=False, command="build",
            error=hint or err,
            path=target.path,
            output={"input_schema": schema_info, "derived_fields": target.derived_fields},
        )


# ── Decode ────────────────────────────────────────────────────────────

def handle_decode(args: dict[str, Any]) -> CmdResult:
    proto = _proto(args.get("proto", "dlt645"))
    _ensure_ir(proto)

    hx = str(args.get("hex", "")).replace(" ", "").replace("\n", "")
    if not hx:
        return CmdResult(success=False, command="decode", error="hex: required")

    from protocol_tool.ir.nodes import ProtocolIR
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine

    ir = ProtocolIR.from_json_file(str(ROOT / "compiled" / f"{proto}.ir.json"))
    de = DecodeEngine(ir, create_builtin_registry())
    try:
        frame = bytes.fromhex(hx)
        result = de.decode(frame)

        # 构建 structured wireforge.result/v1
        wire_fields = _build_wire_fields(result)
        structured = {
            "schema_version": "wireforge.result/v1",
            "operation": "decode",
            "status": "ok",
            "protocol": {"id": proto},
            "resolved": {
                "message_id": result.values.get(result.path_str.split("→")[-1].strip() if "→" in result.path_str else "", ""),
            },
            "frame": _extract_frame(result),
            "payload": _extract_payload(result),
            "wire": {"hex": result.raw_hex, "fields": wire_fields},
            "diagnostics": {
                "checks": [],
                "warnings": result.warnings,
                "errors": [],
            },
        }
        return CmdResult(
            success=True, command="decode",
            path=result.path_str, frame_hex=result.raw_hex,
            structured=structured,
        )
    except Exception as e:
        return CmdResult(success=False, command="decode", error=str(e))


# ── 结构化结果辅助 ────────────────────────────────────────────────────

def _build_wire_fields(result) -> list[dict]:
    """从 DecodeResult.trace 构建 wire.fields 列表。"""
    fields = []
    for ev in result.trace:
        pos = ev.get("position", 0)
        raw = ev.get("raw", "")
        if not raw:
            continue
        raw_bytes = bytes.fromhex(raw)
        fields.append({
            "offset": [pos, pos + len(raw_bytes)],
            "path": f"frame.{ev.get('field', '?')}",
            "wire_hex": raw,
            "label": ev.get("field", ""),
            "value": ev.get("value"),
        })
    return fields


def _extract_frame(result) -> dict:
    """从解码值中提取帧级字段。"""
    vals = result.values
    frame: dict[str, Any] = {}
    frame_keys = {"preamble", "start1", "address", "start2", "control", "length",
                  "total_length", "cs", "checksum", "end"}
    for k in frame_keys:
        if k in vals:
            v = vals[k]
            frame[k] = v
    return frame


def _extract_payload(result) -> dict:
    """从解码值中提取 payload 字段（排除帧级和内部键）。"""
    vals = result.values
    frame_keys = {"preamble", "start1", "address", "start2", "control", "length",
                  "total_length", "cs", "checksum", "end", "data", "user_data"}
    payload: dict[str, Any] = {}
    for k, v in vals.items():
        if k not in frame_keys and not k.startswith(("read_", "csg_", "csg")):
            if isinstance(v, (str, int, float, bool, list)):
                payload[k] = v
            elif isinstance(v, dict):
                payload[k] = v
    return payload


# ── 注册 (命令元数据从 JSON 文件加载) ──────────────────────────────────

# ── Serial ─────────────────────────────────────────────────────────────

def _handle_serial_open(args: dict) -> CmdResult:
    from serial.api import serial_open
    r = serial_open(args)
    d = r.to_dict()
    return CmdResult(success=r.success, command="serial-open",
                     structured=d, error=r.error)


def _handle_serial_send(args: dict) -> CmdResult:
    from serial.api import serial_send
    r = serial_send(args)
    d = r.to_dict()
    return CmdResult(success=r.success, command="serial-send",
                     structured=d, error=r.error)


def _handle_serial_close(args: dict) -> CmdResult:
    from serial.api import serial_close
    r = serial_close(args)
    d = r.to_dict()
    return CmdResult(success=r.success, command="serial-close",
                     structured=d, error=r.error)


def _handle_serial_ports(args: dict) -> CmdResult:
    from serial.api import serial_ports
    r = serial_ports(args)
    d = r.to_dict()
    return CmdResult(success=r.success, command="serial-ports",
                     structured=d, error=r.error)


# ── 注册 ──────────────────────────────────────────────────────────────

def _register_all():
    import json
    cmds_dir = Path(__file__).resolve().parent / "commands"
    handler_map = {
        "build": handle_build, "decode": handle_decode,
        "connect": _handle_serial_open,
        "send": _handle_serial_send,
        "close": _handle_serial_close,
        "ports": _handle_serial_ports,
    }
    for fpath in sorted(cmds_dir.glob("*.json")):
        data = json.loads(fpath.read_text())
        params = [Param(
            name=p["name"], type=p.get("type", "str"),
            required=p.get("required", False), desc=p.get("desc", ""),
            values=p.get("values"), default=p.get("default"),
        ) for p in data.get("params", [])]
        cmd = Command(
            name=data["name"], desc=data.get("desc", ""),
            params=params, enabled=data.get("enabled", True),
            timeout=data.get("timeout", 15000),
        )
        h = handler_map.get(data["name"])
        if h:
            registry.register(cmd, h)

_register_all()
