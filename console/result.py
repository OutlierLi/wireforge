"""WireForge 结果类型 — 稳定 JSON 外壳。

schema_version: wireforge.result/v1

所有结果共享外层结构:
  operation, status, protocol, resolved, frame, payload, wire, diagnostics

Build 和 Decode 的 wire.fields 结构一致。
路由信息仅在 --trace 时返回。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── wire.fields 条目 ───────────────────────────────────────────────────

@dataclass
class WireField:
    """逐字节字段映射 — Build 和 Decode 共用。"""
    offset: tuple[int, int]           # [start, end) 字节偏移
    path: str                         # emit_path，如 "frame.address", "payload.di"
    wire_hex: str                     # 线缆字节 (原始)
    logical_hex: str | None = None    # 逻辑字节 (变换后)，与 wire 相同时为 null
    label: str = ""                   # 显示标签
    description: str = ""             # 描述
    value: Any = None                 # 解码后的语义值

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "offset": list(self.offset),
            "path": self.path,
            "wire_hex": self.wire_hex,
            "label": self.label,
            "value": self.value,
        }
        if self.logical_hex and self.logical_hex != self.wire_hex:
            d["logical_hex"] = self.logical_hex
        if self.description:
            d["description"] = self.description
        return d


# ── 结果基类 ──────────────────────────────────────────────────────────

@dataclass
class WireForgeResult:
    """统一结果外壳。"""
    schema_version: str = "wireforge.result/v1"
    operation: str = ""          # "build" | "decode" | "describe"
    status: str = "ok"           # "ok" | "error"

    protocol: dict[str, str] = field(default_factory=dict)
    resolved: dict[str, Any] = field(default_factory=dict)
    frame: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    wire: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    # 仅在 --trace 时返回
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "status": self.status,
            "protocol": self.protocol,
            "resolved": self.resolved,
            "frame": self.frame,
            "payload": self.payload,
            "wire": self.wire,
            "diagnostics": self.diagnostics,
        }
        if self.trace:
            d["trace"] = self.trace
        # 移除空值
        for key in list(d.keys()):
            if not d[key] and key not in ("status", "schema_version", "operation"):
                del d[key]
        return d


# ── Build Describe ────────────────────────────────────────────────────

@dataclass
class BuildDescribeResult:
    """--resolve 结果: 目标 + input_schema"""
    status: str = "ok"
    protocol: str = ""
    resolved: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": "wireforge.build-describe/v1",
            "status": self.status,
            "protocol": self.protocol,
            "resolved": self.resolved,
            "input_schema": self.input_schema,
        }
