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
from protocol_tool.ir.graph import (
    GraphNode,
    GraphRoute,
    GraphPayload,
    ProtocolGraph,
    protocol_graph_from_ir,
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
    "GraphNode",
    "GraphRoute",
    "GraphPayload",
    "ProtocolGraph",
    "protocol_graph_from_ir",
]
