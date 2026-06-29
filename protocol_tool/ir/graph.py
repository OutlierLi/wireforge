"""Graph projection for protocol IR.

The runtime still consumes ``ProtocolIR`` directly.  This module provides a
small, explicit graph view used by agents, tooling, and tests to reason about
the frame structure without re-parsing YAML or guessing routing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from protocol_tool.ir.nodes import FieldNode, ProtocolIR

GraphNodeType = Literal["const", "field", "route", "virtual", "patch", "end"]


@dataclass(frozen=True)
class GraphNode:
    """One protocol graph node.

    ``route`` is set only for nodes that choose the next payload structure.
    Plain fields are intentionally not promoted to route nodes unless they
    directly perform dispatch in the compiled IR.
    """

    id: str
    name: str
    type: GraphNodeType
    codec: str
    size: int | None = None
    next: str | None = None
    route: str | None = None
    source: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "codec": self.codec,
        }
        if self.size is not None:
            result["size"] = self.size
        if self.next:
            result["next"] = self.next
        if self.route:
            result["route"] = self.route
        if self.source:
            result["source"] = self.source
        if self.params:
            result["params"] = self.params
        return result


@dataclass(frozen=True)
class GraphRoute:
    """A route table projected from ``RouterNode``."""

    id: str
    keys: tuple[str, ...]
    table: dict[str, str] = field(default_factory=dict)
    fallback: str = "error"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "keys": list(self.keys),
            "table": dict(self.table),
            "fallback": self.fallback,
        }
        if self.description:
            result["description"] = self.description
        return result


@dataclass(frozen=True)
class GraphPayload:
    """Payload schema reachable through a graph route."""

    id: str
    name: str
    fields: tuple[GraphNode, ...] = ()
    router_id: str | None = None
    route_key: str | None = None
    message_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
        }
        if self.router_id:
            result["router_id"] = self.router_id
        if self.route_key:
            result["route_key"] = self.route_key
        if self.message_ref:
            result["message_ref"] = self.message_ref
        return result


@dataclass(frozen=True)
class ProtocolGraph:
    """A graph-shaped view of a compiled protocol."""

    protocol: str
    name: str
    start: str
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    routes: dict[str, GraphRoute] = field(default_factory=dict)
    payloads: dict[str, GraphPayload] = field(default_factory=dict)

    def node_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in self.nodes.values():
            counts[node.type] = counts.get(node.type, 0) + 1
        for payload in self.payloads.values():
            for node in payload.fields:
                counts[node.type] = counts.get(node.type, 0) + 1
        return counts

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.start not in self.nodes:
            issues.append(f"start node not found: {self.start}")
        for node in self.nodes.values():
            if node.next and node.next not in self.nodes:
                issues.append(f"{node.id}: next node not found: {node.next}")
            if node.route and node.route not in self.routes:
                issues.append(f"{node.id}: route not found: {node.route}")
        route_targets = {target for route in self.routes.values() for target in route.table.values()}
        missing_targets = sorted(t for t in route_targets if t not in self.payloads)
        for target in missing_targets:
            issues.append(f"route target payload not found: {target}")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "name": self.name,
            "start": self.start,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "routes": {k: v.to_dict() for k, v in self.routes.items()},
            "payloads": {k: v.to_dict() for k, v in self.payloads.items()},
        }


def protocol_graph_from_ir(ir: ProtocolIR) -> ProtocolGraph:
    """Project a compiled ``ProtocolIR`` into a minimal protocol graph."""

    frame_nodes: dict[str, GraphNode] = {}
    frame_fields = list(ir.frame.fields)
    for index, field_node in enumerate(frame_fields):
        node_id = _graph_node_id("frame", field_node.name, index)
        next_id = None
        if index + 1 < len(frame_fields):
            next_id = _graph_node_id("frame", frame_fields[index + 1].name, index + 1)
        graph_node = _field_to_graph_node(node_id, field_node, source=ir.frame.id, next_id=next_id)
        frame_nodes[node_id] = graph_node

    routes = {
        router_id: GraphRoute(
            id=router_id,
            keys=router.key_paths,
            table=dict(router.route_table),
            fallback=router.fallback_policy,
            description=router.description,
        )
        for router_id, router in ir.routers.items()
    }

    payloads: dict[str, GraphPayload] = {}
    for leaf_id, leaf in ir.leaves.items():
        payload_fields = []
        leaf_fields = list(leaf.fields)
        for index, field_node in enumerate(leaf_fields):
            node_id = _graph_node_id(leaf_id, field_node.name, index)
            next_id = None
            if index + 1 < len(leaf_fields):
                next_id = _graph_node_id(leaf_id, leaf_fields[index + 1].name, index + 1)
            payload_fields.append(
                _field_to_graph_node(node_id, field_node, source=leaf_id, next_id=next_id)
            )
        payloads[leaf_id] = GraphPayload(
            id=leaf_id,
            name=leaf.name,
            fields=tuple(payload_fields),
            router_id=leaf.router_id,
            route_key=leaf.route_key,
            message_ref=leaf.message_ref,
        )

    start = _graph_node_id("frame", frame_fields[0].name, 0) if frame_fields else ""
    return ProtocolGraph(
        protocol=ir.protocol,
        name=ir.name,
        start=start,
        nodes=frame_nodes,
        routes=routes,
        payloads=payloads,
    )


def _field_to_graph_node(
    node_id: str,
    field_node: FieldNode,
    *,
    source: str,
    next_id: str | None,
) -> GraphNode:
    node_type = _node_type(field_node)
    params = dict(field_node.params)
    if field_node.length_from:
        params["length_from"] = field_node.length_from
    if field_node.length_adjust:
        params["length_adjust"] = field_node.length_adjust
    if field_node.transforms:
        params["transforms"] = [
            {"algorithm": t.algorithm, "params": t.params}
            for t in field_node.transforms
        ]
    if field_node.condition:
        params["condition"] = {
            "kind": field_node.condition.kind,
            "field_ref": field_node.condition.field_ref,
            "value": field_node.condition.value,
        }

    route = None
    if node_type in {"route", "virtual"}:
        route = field_node.params.get("router")

    return GraphNode(
        id=node_id,
        name=field_node.name,
        type=node_type,
        codec=field_node.type_ref,
        size=_field_size(field_node),
        next=next_id,
        route=route,
        source=source,
        params=params,
    )


def _node_type(field_node: FieldNode) -> GraphNodeType:
    codec = field_node.type_ref
    name = field_node.name.lower()
    if codec == "routed_payload":
        return "virtual"
    if name == "end" and codec == "const":
        return "end"
    if codec in {"sum8", "checksum", "xor8", "crc8", "crc16_modbus", "crc16_ccitt"}:
        return "patch"
    if name in {"length", "data_length", "total_length", "checksum", "cs", "crc"}:
        return "patch"
    if codec in {"const", "const_repeat"}:
        return "const"
    return "field"


def _field_size(field_node: FieldNode) -> int | None:
    if field_node.length is not None:
        return field_node.length
    codec = field_node.type_ref
    if codec in {"uint8", "int8", "sum8", "checksum", "xor8", "crc8", "bitset", "const"}:
        return 1
    if codec in {"uint16", "uint16_le", "uint16_be", "int16", "crc16_modbus", "crc16_ccitt"}:
        return 2
    if codec in {"uint24_le", "uint24_be"}:
        return 3
    if codec in {"uint32", "uint32_le", "uint32_be", "int32"}:
        return 4
    value = field_node.params.get("value")
    if codec == "const_repeat":
        return field_node.params.get("default") or field_node.params.get("min")
    if isinstance(value, str):
        return max(1, len(value.replace(" ", "")) // 2)
    return None


def _graph_node_id(scope: str, name: str, index: int) -> str:
    clean_scope = scope.replace(":", ".")
    return f"{clean_scope}.{index:02d}.{name}"
