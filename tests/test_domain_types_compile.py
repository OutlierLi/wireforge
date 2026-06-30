"""Compile tests for domain extended types (node_address)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"


def test_compile_extension_with_node_address_array():
    from protocol_tool.compiler.pipeline import compile_protocol

    compile_protocol(str(REGISTRY), "csg_2016", output_dir=str(ROOT / "compiled"))
    ir_path = ROOT / "compiled" / "csg_2016.ir.json"
    assert ir_path.exists()
    text = ir_path.read_text(encoding="utf-8")
    assert "E8020402" in text
    assert "slave_addrs" in text
