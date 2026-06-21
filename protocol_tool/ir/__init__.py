"""Intermediate Representation data structures.

These are pure dataclasses — no logic, no dependencies.
They represent the output of the compiler and the input to the runtime.
"""

from protocol_tool.ir.nodes import (
    FieldNode,
    RouterNode,
    LeafNode,
    FrameNode,
    ProtocolIR,
    TransformSpec,
    ConditionSpec,
    BuildPlan,
)

__all__ = [
    "FieldNode",
    "RouterNode",
    "LeafNode",
    "FrameNode",
    "ProtocolIR",
    "TransformSpec",
    "ConditionSpec",
    "BuildPlan",
]
