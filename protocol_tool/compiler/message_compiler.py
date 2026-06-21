"""Message compiler — messages/*.yaml → LeafNode + Bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from protocol_tool.ir.nodes import LeafNode, FieldNode, BuildPlan

if TYPE_CHECKING:
    from protocol_tool.compiler.loader import CompilationUnit
    from protocol_tool.compiler.resolver import Resolver
    from protocol_tool.compiler.frame_compiler import FrameCompiler


@dataclass
class MessageBinding:
    """Intermediate: a message's registration to a router."""

    message_id: str
    router_id: str
    route_key_raw: list[Any]  # Raw key values from YAML match
    direction: str = ""
    leaf_node_id: str = ""


class MessageCompiler:
    """Compiles message YAML files into LeafNodes and MessageBindings."""

    def __init__(
        self,
        unit: CompilationUnit,
        resolver: Resolver,
        frame_compiler: FrameCompiler,
    ) -> None:
        self.unit = unit
        self.resolver = resolver
        self.frame_compiler = frame_compiler

    def compile(self) -> tuple[dict[str, LeafNode], list[MessageBinding]]:
        """Compile all messages into LeafNodes and Bindings.

        Returns (leaves_dict, bindings_list).
        """
        leaves: dict[str, LeafNode] = {}
        bindings: list[MessageBinding] = []

        for msg_yaml in self.unit.message_data:
            # Support both single message and messages list
            messages = msg_yaml.get("messages", [msg_yaml])
            if not isinstance(messages, list):
                messages = [msg_yaml]

            for msg in messages:
                leaf, binding = self._compile_message(msg)
                if leaf:
                    leaves[leaf.id] = leaf
                if binding:
                    bindings.append(binding)

        return leaves, bindings

    def _compile_message(
        self,
        msg: dict[str, Any],
    ) -> tuple[LeafNode | None, MessageBinding | None]:
        """Compile one message definition."""
        msg_id = msg.get("id", "")
        if not msg_id:
            return None, None

        kind = msg.get("kind", "message")
        if kind != "message":
            return None, None

        proto = self.unit.protocol_name
        node_id = f"node:{proto}.{msg_id}"

        # Compile body fields
        body = msg.get("body", {})
        fields: list[FieldNode] = []
        if body.get("type") == "struct" and "fields" in body:
            fields = self.frame_compiler._compile_fields(
                body["fields"],
                prefix=node_id,
            )

        leaf = LeafNode(
            id=node_id,
            name=msg_id,
            fields=tuple(fields),
            message_ref=msg_id,
            router_id=msg.get("router", ""),
        )

        # Build route binding
        router_id = msg.get("router", "")
        match = msg.get("match", {})
        route_key_raw = list(match.values()) if match else []

        binding = MessageBinding(
            message_id=msg_id,
            router_id=router_id,
            route_key_raw=route_key_raw,
            direction=msg.get("direction", ""),
            leaf_node_id=node_id,
        )

        return leaf, binding
