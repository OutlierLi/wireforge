"""Router — selects the next IR node based on already-parsed field values.

Routers DO NOT consume bytes. They only choose which node decodes next.
This is the core innovation over the old project — dispatch is a first-class
concept, not hardcoded in protocol-specific classes.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import RouterNode
    from protocol_tool.runtime.context import DecodeContext


class RouteError(ValueError):
    """Raised when a router cannot find a target and fallback is 'error'."""
    pass


class Router:
    """Resolves a route key from context values to a target node ID.

    Parameters
    ----------
    node:
        The RouterNode IR definition containing key_paths, route_table, and fallback.
    """

    def __init__(self, node: RouterNode) -> None:
        self.node = node

    def resolve(self, context: DecodeContext) -> str | None:
        """Extract route key from context, look up route_table, return target node ID.

        Returns None if fallback is 'raw' or 'preserve_payload' and no route matches.
        Raises RouteError if fallback is 'error' and no route matches.
        """
        keys: list[Any] = []
        for path in self.node.key_paths:
            try:
                value = context.get(path)
            except KeyError:
                # Key not yet parsed — cannot route
                if self.node.fallback_policy == "error":
                    raise RouteError(
                        f"Router {self.node.id!r}: required key path {path!r} "
                        f"not found in context. Available: {sorted(context.values.keys())}"
                    )
                return self._apply_fallback()

            keys.append(self._normalize_key(value))

        key_str = self._serialize_key(keys)
        target = self.node.route_table.get(key_str)

        if target is not None:
            return target

        # No match — apply fallback
        return self._apply_fallback(key_str)

    def _apply_fallback(self, attempted_key: str | None = None) -> str | None:
        policy = self.node.fallback_policy
        if policy == "error":
            msg = f"Router {self.node.id!r}: no route for key {attempted_key}"
            if attempted_key:
                available = sorted(self.node.route_table.keys())
                msg += f". Available keys: {available}"
            raise RouteError(msg)
        elif policy == "raw":
            return "raw_remaining"
        elif policy == "preserve_payload":
            return None
        return None

    @staticmethod
    def _normalize_key(value: Any) -> Any:
        """Normalize a key value to a consistent type for lookup."""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            # Try to interpret as hex
            text = value.strip().upper().replace(" ", "")
            if text.startswith("0X"):
                return int(text, 16)
            if all(c in "0123456789ABCDEF" for c in text) and text:
                return text  # Keep as string for DI-style keys
            return value
        return value

    @staticmethod
    def _serialize_key(keys: list[Any]) -> str:
        """Serialize a key list to the string used in route_table.

        Uses JSON for tuple serialization: [17, 1] → '[17,1]'
        String keys are preserved as-is for DI-style lookups.
        """
        # If single key and it's a string, use it directly (DI-style)
        if len(keys) == 1 and isinstance(keys[0], str):
            return keys[0]
        return json.dumps(keys, separators=(",", ":"), sort_keys=True)

    # -- Build-time helpers --

    def route_for_message(self, message_id: str) -> str | None:
        """Find the route key that leads to a given message (by leaf node ID).

        Used during build to reconstruct the route chain from a message ID.
        """
        for key_str, target_id in self.node.route_table.items():
            if target_id == message_id:
                return key_str
        return None

    def leaf_ids(self) -> list[str]:
        """Return all leaf node IDs reachable through this router."""
        return list(self.node.route_table.values())
