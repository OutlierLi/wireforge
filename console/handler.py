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
    """命令执行结果。"""
    success: bool
    command: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    path: str = ""          # 路由调用链
    frame_hex: str = ""     # 构造/解析的报文

    def to_dict(self) -> dict:
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
        return CmdResult(
            success=True, command="build",
            path=target.path, frame_hex=frame_hex,
            output={"protocol": target.protocol, "path": target.path},
        )
    except Exception as e:
        return CmdResult(success=False, command="build", error=str(e),
                         path=target.path)


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
        values = {}
        for k, v in result.values.items():
            if isinstance(v, dict):
                values[k] = v
            elif not k.startswith(("csg_", "read_")):
                values[k] = v
        return CmdResult(
            success=True, command="decode",
            path=result.path_str, frame_hex=result.raw_hex,
            output={"protocol": proto, "values": values, "warnings": result.warnings},
        )
    except Exception as e:
        return CmdResult(success=False, command="decode", error=str(e))


# ── 注册 (命令元数据从 JSON 文件加载) ──────────────────────────────────

def _register_all():
    import json
    cmds_dir = Path(__file__).resolve().parent / "commands"
    handler_map = {"build": handle_build, "decode": handle_decode}
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
