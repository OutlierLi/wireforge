"""Router builder — collects bindings and builds route tables."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from protocol_tool.ir.nodes import RouterNode

if TYPE_CHECKING:
    from protocol_tool.compiler.loader import CompilationUnit
    from protocol_tool.compiler.message_compiler import MessageBinding
    from protocol_tool.compiler.variant_compiler import VariantBinding


class RouterBuilder:
    """Builds RouterNode route tables from MessageBindings and VariantBindings."""

    def __init__(self, unit: CompilationUnit) -> None:
        self.unit = unit

    def build(
        self,
        message_bindings: list[MessageBinding],
        variant_bindings: list[VariantBinding],
    ) -> dict[str, RouterNode]:
        """Build all router nodes.

        Parameters
        ----------
        message_bindings:
            From MessageCompiler.
        variant_bindings:
            From VariantCompiler.

        Returns
        -------
        Dict of router_id → RouterNode with populated route_tables.
        """
        routers: dict[str, RouterNode] = {}

        # Collect all unique router IDs
        router_ids: set[str] = set()
        for b in message_bindings:
            if b.router_id:
                router_ids.add(b.router_id)
        for b in variant_bindings:
            if b.router_id:
                router_ids.add(b.router_id)

        # Get router definitions from protocol.yaml
        router_defs = self.unit.protocol_data.get("routers", {})
        router_ids.update(self._collect_routed_payload_routers())

        for router_id in router_ids:
            # Find router definition
            router_def = self._find_router_def(router_defs, router_id)

            key_paths_raw = router_def.get("keys", router_def.get("key_paths", []))
            # Handle selector_field as single-element key_paths
            if not key_paths_raw and router_def.get("selector_field"):
                key_paths_raw = [router_def["selector_field"]]
            fallback = router_def.get("fallback", "error")

            # Collect bindings for this router
            route_table: dict[str, str] = {}
            seen_keys: dict[str, str] = {}  # For conflict detection

            for b in message_bindings:
                if b.router_id == router_id:
                    key_str = self._normalize_route_key(b.route_key_raw)
                    if key_str in seen_keys:
                        raise ValueError(
                            f"Router {router_id!r}: duplicate route key {key_str} "
                            f"for messages {seen_keys[key_str]!r} and {b.message_id!r}"
                        )
                    seen_keys[key_str] = b.message_id
                    route_table[key_str] = b.leaf_node_id

            for b in variant_bindings:
                if b.router_id == router_id:
                    key_str = self._normalize_route_key(b.route_key_raw)
                    if key_str in seen_keys:
                        raise ValueError(
                            f"Router {router_id!r}: duplicate route key {key_str} "
                            f"for variant {b.variant_id!r} (conflicts with {seen_keys[key_str]!r})"
                        )
                    seen_keys[key_str] = b.variant_id
                    route_table[key_str] = b.leaf_node_id

            routers[router_id] = RouterNode(
                id=router_id,
                key_paths=tuple(key_paths_raw),
                route_table=route_table,
                fallback_policy=fallback,
                description=router_def.get("description", ""),
            )

        return routers

    def _collect_routed_payload_routers(self) -> set[str]:
        router_ids: set[str] = set()

        def walk_fields(fields: list[Any]) -> None:
            for field in fields or []:
                if not isinstance(field, dict):
                    continue
                if field.get("type") == "routed_payload":
                    router = field.get("router")
                    if router:
                        router_ids.add(str(router))
                if field.get("type") == "struct":
                    walk_fields(field.get("fields") or [])

        for msg_yaml in self.unit.message_data:
            messages = msg_yaml.get("messages", [msg_yaml])
            if not isinstance(messages, list):
                messages = [msg_yaml]
            for msg in messages:
                if msg.get("kind") != "message":
                    continue
                body = msg.get("body") or {}
                if body.get("type") == "struct":
                    walk_fields(body.get("fields") or [])

        return router_ids

    @staticmethod
    def _find_router_def(
        router_defs: dict | list,
        router_id: str,
    ) -> dict[str, Any]:
        """Find a router definition by ID in protocol.yaml."""
        if isinstance(router_defs, dict):
            # Routers keyed by name
            if router_id in router_defs:
                return router_defs[router_id]
            # Try "main", "di_router", etc.
            for key, val in router_defs.items():
                if isinstance(val, dict) and val.get("id") == router_id:
                    return val
        elif isinstance(router_defs, list):
            for item in router_defs:
                if isinstance(item, dict) and item.get("id") == router_id:
                    return item
        return {}

    @staticmethod
    def _normalize_route_key(raw_keys: list[Any]) -> str:
        """Normalize a list of raw route key values to the serialized string form.

        Handles:
        - Hex strings: "0x11" → 17, stored as '[17]'
        - Plain strings (DI codes): "00010000" → "00010000"
        - Mixed: [17, 1] → '[17,1]'
        """
        normalized = []
        for val in raw_keys:
            if isinstance(val, int):
                normalized.append(val)
            elif isinstance(val, str):
                val = val.strip()
                if val.lower().startswith("0x"):
                    normalized.append(int(val, 16))
                elif val.endswith("h") or val.endswith("H"):
                    normalized.append(int(val[:-1], 16))
                else:
                    # Keep as-is (DI codes, etc.)
                    normalized.append(val.upper())
            else:
                normalized.append(val)

        if len(normalized) == 1 and isinstance(normalized[0], str):
            return normalized[0]
        return json.dumps(normalized, separators=(",", ":"))
