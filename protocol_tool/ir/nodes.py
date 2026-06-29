"""IR data structures — pure frozen dataclasses representing compiled protocol definitions.

These are the single source of truth for both the compiler output and runtime input.
No logic, no methods beyond serialization helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Field-level types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransformSpec:
    """A wire-level byte transformation applied before decode / after encode.

    Example:
        TransformSpec(algorithm="add_33h")   – add 0x33 to each byte
        TransformSpec(algorithm="sub_33h")   – subtract 0x33 from each byte
        TransformSpec(algorithm="reverse_bytes", params={"width": 2})
    """

    algorithm: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConditionSpec:
    """A condition that must be satisfied for a field to be present."""

    kind: Literal["equals", "not_equals", "exists", "bit_set"]
    field_ref: str  # dotted path to another field, e.g. "control.add"
    value: Any = None


@dataclass(frozen=True)
class FieldNode:
    """A single field within a frame, message, or variant.

    Parameters
    ----------
    id:
        Unique identifier within the parent scope, e.g. "frame.control".
    name:
        Human-readable name, e.g. "control".
    type_ref:
        Key into the codec registry: "uint8", "bcd", "bitset", "const",
        "const_repeat", "routed_payload", "checksum", "hex", "bytes",
        "ascii", "struct", "array", "enum".
    params:
        Codec-specific parameters:
        - const: {"value": 0x68}
        - const_repeat: {"value": 0xFE, "min": 0, "max": 4}
        - uint*: {"byte_order": "little"}
        - bcd: {"length": 6, "byte_order": "little", "canonical_format": "decimal_string"}
        - ascii: {"length": N, "byte_order": "little"} (default, same as bcd/hex)
        - bitset: {"bits": [{"name": "func", "offset": 0, "width": 5}, ...]}
        - checksum: {"algorithm": "sum8", "cover": {"start": "control", "end": "data"}}
        - routed_payload: {"router": "main", "length_from": "length"}
        - hex: {"length": 4}
        - bytes: {"length": 8}
        - array: {"item_type": "...", "count_ref": "n"}
        - enum: {"values": {0: "ok", 1: "error"}}
    length:
        Explicit fixed length in bytes, or None if determined by other means.
    length_from:
        Name of another field whose *value* provides the length.
    length_adjust:
        Adjustment to apply to the referenced length (e.g. -2 for header bytes).
    transforms:
        Wire-level transforms applied to the raw bytes before decode / after encode.
        Decode order: transforms applied decode[0], decode[1], ... then codec.decode.
        Encode order:  codec.encode then transforms applied encode[-1], encode[-2], ...
    condition:
        Conditional presence — field is skipped if condition evaluates false.
    default:
        Default value when building if not provided.
    optional:
        If True, field may be absent during building.
    """

    id: str
    name: str
    type_ref: str
    params: dict[str, Any] = field(default_factory=dict)
    length: int | None = None
    length_from: str | None = None
    length_adjust: int = 0
    transforms: tuple[TransformSpec, ...] = ()
    condition: ConditionSpec | None = None
    default: Any = None
    optional: bool = False

    @property
    def effective_length(self) -> int | None:
        """Return the explicit length if set."""
        return self.length

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type_ref": self.type_ref,
        }
        if self.params:
            d["params"] = self.params
        if self.length is not None:
            d["length"] = self.length
        if self.length_from is not None:
            d["length_from"] = self.length_from
        if self.length_adjust != 0:
            d["length_adjust"] = self.length_adjust
        if self.transforms:
            d["transforms"] = [
                {"algorithm": t.algorithm, "params": t.params} if t.params else {"algorithm": t.algorithm}
                for t in self.transforms
            ]
        if self.condition is not None:
            d["condition"] = {
                "kind": self.condition.kind,
                "field_ref": self.condition.field_ref,
                "value": self.condition.value,
            }
        if self.default is not None:
            d["default"] = self.default
        if self.optional:
            d["optional"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldNode:
        """Deserialize from a dict."""
        transforms = tuple(
            TransformSpec(
                algorithm=t["algorithm"],
                params=t.get("params", {}),
            )
            for t in d.get("transforms", [])
        )
        condition = None
        if "condition" in d:
            condition = ConditionSpec(
                kind=d["condition"]["kind"],
                field_ref=d["condition"]["field_ref"],
                value=d["condition"].get("value"),
            )
        return cls(
            id=d["id"],
            name=d["name"],
            type_ref=d["type_ref"],
            params=d.get("params", {}),
            length=d.get("length"),
            length_from=d.get("length_from"),
            length_adjust=d.get("length_adjust", 0),
            transforms=transforms,
            condition=condition,
            default=d.get("default"),
            optional=d.get("optional", False),
        )


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouterNode:
    """A router selects the next IR node based on already-parsed field values.

    Routers DO NOT consume bytes — they only choose which node decodes next.

    Parameters
    ----------
    id:
        Unique router identifier, e.g. "router:dlt645.main".
    key_paths:
        Ordered list of dotted field paths that form the route key.
        e.g. ["control.func", "control.dir"] means route key = (ctx["control"]["func"], ctx["control"]["dir"]).
    route_table:
        Serialized route key → target node id.
        Keys are JSON-encoded tuples, e.g. '["17","1"]' → "node:dlt645.read_data_response".
    fallback_policy:
        - "error": raise RouteError
        - "raw": return a synthetic raw_remaining node
        - "preserve_payload": keep raw bytes as-is
    """

    id: str
    key_paths: tuple[str, ...]
    route_table: dict[str, str] = field(default_factory=dict)
    fallback_policy: Literal["error", "raw", "preserve_payload"] = "error"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key_paths": list(self.key_paths),
            "route_table": self.route_table,
            "fallback_policy": self.fallback_policy,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RouterNode:
        return cls(
            id=d["id"],
            key_paths=tuple(d["key_paths"]),
            route_table=d.get("route_table", {}),
            fallback_policy=d.get("fallback_policy", "error"),
            description=d.get("description", ""),
        )


@dataclass(frozen=True)
class LeafNode:
    """A terminal node — the payload fields of a message or variant.

    Parameters
    ----------
    id:
        Unique node identifier, e.g. "node:dlt645.read_data_response".
    name:
        Human-readable name.
    fields:
        The fields that make up this message/variant payload.
    message_ref:
        Original message YAML identifier.
    router_id:
        The router this leaf is registered to (for build-time message lookup).
    route_key:
        The serialized route key this leaf matches (for build-time reverse lookup).
    description:
        Human-readable protocol description from the source YAML.
    """

    id: str
    name: str
    fields: tuple[FieldNode, ...] = ()
    message_ref: str | None = None
    router_id: str | None = None
    route_key: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
        }
        if self.message_ref:
            d["message_ref"] = self.message_ref
        if self.router_id:
            d["router_id"] = self.router_id
        if self.route_key:
            d["route_key"] = self.route_key
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LeafNode:
        return cls(
            id=d["id"],
            name=d["name"],
            fields=tuple(FieldNode.from_dict(f) for f in d.get("fields", [])),
            message_ref=d.get("message_ref"),
            router_id=d.get("router_id"),
            route_key=d.get("route_key"),
            description=d.get("description", ""),
        )


@dataclass(frozen=True)
class FrameNode:
    """The outer frame structure of a protocol.

    A frame is a linear sequence of FieldNodes that define how to read/write
    the protocol envelope: start markers, addresses, control bytes, length fields,
    payload areas, checksums, and end markers.

    Parameters
    ----------
    id:
        Frame identifier, usually "frame".
    fields:
        Ordered sequence of fields in the frame envelope.
    """

    id: str
    fields: tuple[FieldNode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FrameNode:
        return cls(
            id=d["id"],
            fields=tuple(FieldNode.from_dict(f) for f in d.get("fields", [])),
        )


# ---------------------------------------------------------------------------
# Top-level IR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildPlan:
    """Pre-computed build plan for constructing a message.

    Records which routers to traverse and what route keys to set for each
    router along the path from frame → message → variant.
    """

    message_id: str
    frame_id: str = "frame"
    route_chain: tuple[tuple[str, str], ...] = ()
    # Each entry: (router_id, serialized_route_key)
    # e.g. (("router:main", '["17","1"]'), ("router:di", '["00010000"]'))

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "frame_id": self.frame_id,
            "route_chain": [
                [router_id, route_key] for router_id, route_key in self.route_chain
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BuildPlan:
        return cls(
            message_id=d["message_id"],
            frame_id=d.get("frame_id", "frame"),
            route_chain=tuple(
                (router_id, route_key) for router_id, route_key in d.get("route_chain", [])
            ),
        )


@dataclass(frozen=True)
class ProtocolIR:
    """Top-level compiled intermediate representation for a single protocol.

    This is the output of the compiler and the sole input to the runtime.
    Serialized as protocol.ir.json.

    Parameters
    ----------
    version:
        IR format version (currently 1).
    protocol:
        Protocol identifier, e.g. "dlt645_2007".
    name:
        Human-readable protocol name.
    frame:
        The outer frame structure.
    routers:
        All routers, keyed by router ID.
    leaves:
        All message/variant leaf nodes, keyed by leaf ID.
    build_plans:
        Pre-computed build plans, keyed by message_id.
        Allows BuildEngine to determine route chain without scanning.
    algorithms:
        Algorithm parameter references shared across fields.
    metadata:
        Arbitrary metadata (source files, compile timestamp, etc.).
    """

    version: int = 1
    protocol: str = ""
    name: str = ""
    frame: FrameNode = field(default_factory=lambda: FrameNode(id="frame"))
    routers: dict[str, RouterNode] = field(default_factory=dict)
    leaves: dict[str, LeafNode] = field(default_factory=dict)
    build_plans: dict[str, BuildPlan] = field(default_factory=dict)
    algorithms: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- Node index (built lazily, not serialized directly) --

    def node_index(self) -> dict[str, FrameNode | RouterNode | LeafNode]:
        """Build a unified node index: node_id → node."""
        index: dict[str, FrameNode | RouterNode | LeafNode] = {}
        index[self.frame.id] = self.frame
        for router in self.routers.values():
            index[router.id] = router
        for leaf in self.leaves.values():
            index[leaf.id] = leaf
        return index

    def get_node(self, node_id: str) -> FrameNode | RouterNode | LeafNode:
        """Look up any node by ID."""
        if node_id == self.frame.id:
            return self.frame
        if node_id in self.routers:
            return self.routers[node_id]
        if node_id in self.leaves:
            return self.leaves[node_id]
        raise KeyError(f"Unknown node id: {node_id}")

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "version": self.version,
            "protocol": self.protocol,
            "name": self.name,
            "frame": self.frame.to_dict(),
            "routers": {k: v.to_dict() for k, v in self.routers.items()},
            "leaves": {k: v.to_dict() for k, v in self.leaves.items()},
            "build_plans": {k: v.to_dict() for k, v in self.build_plans.items()},
            "algorithms": self.algorithms,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProtocolIR:
        """Deserialize from a dict."""
        return cls(
            version=d.get("version", 1),
            protocol=d.get("protocol", ""),
            name=d.get("name", ""),
            frame=FrameNode.from_dict(d["frame"]),
            routers={k: RouterNode.from_dict(v) for k, v in d.get("routers", {}).items()},
            leaves={k: LeafNode.from_dict(v) for k, v in d.get("leaves", {}).items()},
            build_plans={
                k: BuildPlan.from_dict(v) for k, v in d.get("build_plans", {}).items()
            },
            algorithms=d.get("algorithms", {}),
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, text: str) -> ProtocolIR:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_json_file(cls, path: str) -> ProtocolIR:
        """Load from a .ir.json file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())
