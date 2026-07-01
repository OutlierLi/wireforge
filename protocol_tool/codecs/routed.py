"""RoutedPayload codec — delegates to a router to select the target node.

This is the bridge between codec layer and router dispatch.
When the engine encounters a "routed_payload" field, it:
1. Reads raw bytes (length determined by length_from or remaining)
2. Applies wire transforms (e.g. add_33h / sub_33h for DLT645)
3. Creates a sub-reader for the payload bytes
4. Calls Router.resolve() to find the target LeafNode
5. Pushes a StackFrame and decodes the LeafNode's fields
6. Pops the StackFrame and returns the decoded values
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec, ByteWriter
from protocol_tool.runtime.router import RouteError

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext



class RoutedPayloadCodec(FieldCodec):
    """Delegates payload decoding to a router and its target LeafNode.

    This codec requires the engine to have set up:
    - codec._engine: reference to the DecodeEngine (for node lookup)
    - codec._ir: reference to the ProtocolIR

    Parameters (from FieldNode.params):
        router: router ID to use for dispatch
        length_from: field name whose value determines payload length
        length_adjust: adjustment to apply to the referenced length
        transforms: wire-level transforms (e.g. add_33h/sub_33h for DLT645)
    """

    def __init__(self) -> None:
        self._engine: Any = None
        self._ir: Any = None

    def set_engine(self, engine: Any, ir: Any) -> None:
        """Called by DecodeEngine after construction to wire up routing."""
        self._engine = engine
        self._ir = ir

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> dict[str, Any] | bytes:
        # Determine payload length
        length = self._payload_length(field, reader, context)
        if length is None:
            # Read all remaining bytes
            length = reader.remaining()
        if length <= 0:
            return {}

        raw_payload = reader.read(length)

        # Apply wire transforms (e.g. DLT645 data domain +33H encoding)
        from protocol_tool.codecs.transforms import apply_transforms_decode
        raw_payload = apply_transforms_decode(raw_payload, field.transforms)

        # Save raw section for checksum (use field name as key)
        context.raw_sections[field.name] = raw_payload

        # Create sub-reader for the payload
        from protocol_tool.runtime.reader import DecodeReader as DR
        sub_reader = DR(raw_payload, 0, len(raw_payload))

        # Resolve router
        router_id = field.params.get("router", "")
        if not router_id or not self._ir:
            # No router configured — return raw bytes
            return raw_payload

        router_node = self._ir.routers.get(router_id)
        if router_node is None:
            context.warning(f"Unknown router: {router_id!r}, returning raw payload")
            return raw_payload

        # Resolve route target
        from protocol_tool.runtime.router import Router
        router = Router(router_node)
        target_id = router.resolve(context)

        if target_id is None:
            # Fallback: return raw bytes
            return raw_payload

        # Route to a raw_remaining fallback
        if target_id == "raw_remaining" or target_id == "raw_leaf":
            return sub_reader.read_remaining()

        # Decode target leaf node
        if self._engine is not None:
            return self._engine._decode_leaf(target_id, sub_reader, context)
        return raw_payload

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        """Encode payload by resolving the target message and encoding its fields.

        The BuildContext must have:
        - message_id: the message being built
        - route_chain: explicit route chain for the message
        """
        # Determine which leaf to encode.
        # For frame-level fields: use build_plan from message_id.
        # For nested fields: resolve via the field's own router using context values.
        import json
        leaf = None
        router_id = field.params.get("router", "")

        # Try build_plan first (for frame-level routing)
        message_id = context.message_id
        if message_id and self._ir and not leaf:
            build_plan = self._ir.build_plans.get(message_id)
            if build_plan:
                for rid, route_key in build_plan.route_chain:
                    if rid == router_id or not router_id:
                        rnode = self._ir.routers.get(rid)
                        if rnode:
                            lid = rnode.route_table.get(route_key)
                            if lid:
                                leaf = self._ir.leaves.get(lid)

        # Try resolving via the field's router and context values (for nested routing)
        if not leaf and router_id and router_id in (self._ir.routers if self._ir else {}):
            rnode = self._ir.routers[router_id]
            # Build key from context values
            keys = []
            for path in rnode.key_paths:
                try:
                    keys.append(context.get(path))
                except KeyError:
                    keys.append(0)
            key_str = json.dumps(keys, separators=(",", ":")) if len(keys) > 1 else (
                keys[0] if isinstance(keys[0], str) else json.dumps(keys)
            )
            lid = rnode.route_table.get(key_str)
            if lid:
                leaf = self._ir.leaves.get(lid)

        if leaf is None:
            if router_id and self._ir:
                rnode = self._ir.routers.get(router_id)
                if rnode and rnode.fallback_policy == "raw":
                    payload = self._coerce_raw_payload(field, value, context)
                    if payload is not None:
                        from protocol_tool.codecs.transforms import apply_transforms_encode
                        payload = apply_transforms_encode(payload, field.transforms)
                        context.raw_sections[field.name] = payload
                        writer.write(payload)
                        return
            if router_id:
                raise RouteError(
                    f"Build error: no route found for router {router_id!r} "
                    f"with field {field.name!r}. Check route_table."
                )
            payload = self._coerce_raw_payload(field, value, context)
            if payload is None:
                raise RouteError(
                    f"Build error: no message_id, no router, and no raw value "
                    f"for routed_payload field {field.name!r}"
                )
        else:
            # Encode leaf fields using context.values (user-provided build values)
            sub_writer = ByteWriter()
            if self._engine is not None:
                self._engine._encode_leaf(leaf, context.values, sub_writer, context)
            payload = sub_writer.bytes()

        # Apply wire transforms (e.g. DLT645 data domain +33H encoding)
        from protocol_tool.codecs.transforms import apply_transforms_encode
        payload = apply_transforms_encode(payload, field.transforms)

        # Save for checksum
        context.raw_sections[field.name] = payload

        writer.write(payload)

    @staticmethod
    def _coerce_raw_payload(field: FieldNode, value: Any, context: BuildContext) -> bytes | None:
        candidates = [value, context.values.get(field.name)]
        for item in candidates:
            if isinstance(item, bytes):
                return item
            if isinstance(item, dict) and "raw" in item:
                return bytes.fromhex(str(item["raw"]))
            if item is not None and item != "":
                return bytes.fromhex(str(item))
        return None

    @staticmethod
    def _payload_length(
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> int | None:
        if field.length is not None:
            return field.length
        if field.length_from is not None:
            val = context.values.get(field.length_from)
            if val is not None and isinstance(val, int):
                return val + field.length_adjust
        return None
