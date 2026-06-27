"""Variant compiler — variants/*.yaml → LeafNode modifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from protocol_tool.ir.nodes import LeafNode, FieldNode

if TYPE_CHECKING:
    from protocol_tool.compiler.loader import CompilationUnit
    from protocol_tool.compiler.resolver import Resolver
    from protocol_tool.compiler.frame_compiler import FrameCompiler


@dataclass
class VariantBinding:
    """A variant's registration to a sub-router."""

    variant_id: str
    router_id: str
    route_key_raw: list[Any]
    base_message_id: str
    leaf_node_id: str


class VariantCompiler:
    """Compiles variant YAML files into VariantBindings and LeafNodes."""

    def __init__(
        self,
        unit: CompilationUnit,
        resolver: Resolver,
        frame_compiler: FrameCompiler,
    ) -> None:
        self.unit = unit
        self.resolver = resolver
        self.frame_compiler = frame_compiler

    def compile(
        self,
        base_leaves: dict[str, LeafNode],
    ) -> tuple[dict[str, LeafNode], list[VariantBinding]]:
        """Compile variants, modifying base leaf nodes when overrides are present.

        Returns (all_leaves_dict, variant_bindings).
        """
        leaves: dict[str, LeafNode] = dict(base_leaves)
        bindings: list[VariantBinding] = []

        for var_yaml in self.unit.variant_data:
            # Support: single variant dict, or {"variants": [...]} list
            variants = var_yaml.get("variants", [var_yaml])
            if not isinstance(variants, list):
                variants = [var_yaml]

            for var in variants:
                new_leaves, new_bindings = self._compile_variant(var)
                leaves.update(new_leaves)
                bindings.extend(new_bindings)

        return leaves, bindings

    def _compile_variant(
        self,
        var: dict[str, Any],
    ) -> tuple[dict[str, LeafNode], list[VariantBinding]]:
        """Compile one variant entry.

        Supports two patterns:
        1. Standalone variant with body:
           kind: variant, id: ..., router: ..., match: {di: "00010000"}, body: {type: struct, fields: [...]}
        2. Base-message override:
           kind: variant, router: ..., entries: [{match: {...}, base_message: ..., override_fields: [...]}]
        """
        kind = var.get("kind", "variant")
        if kind != "variant":
            return {}, []

        router_id = var.get("router", "")
        entries = var.get("entries", [])
        if not entries:
            # Standalone variant — var itself is the entry
            entries = [var]

        leaves: dict[str, LeafNode] = {}
        bindings: list[VariantBinding] = []

        for entry in entries:
            match = entry.get("match", {})
            route_key_raw = list(match.values())
            var_id = entry.get("id", f"{router_id}.variant")
            proto = self.unit.protocol_name
            node_id = f"node:{proto}.{var_id}"

            # Check if this variant has its own body (standalone)
            body = entry.get("body", {})
            if body.get("type") == "struct" and "fields" in body:
                # Standalone variant — compile body fields directly
                fields = self.frame_compiler._compile_fields(
                    body["fields"],
                    prefix=node_id,
                )
                leaf = LeafNode(
                    id=node_id,
                    name=var_id,
                    fields=tuple(fields),
                    message_ref=var_id,
                    router_id=router_id,
                    route_key=RouterBuilder.normalize_route_key(route_key_raw),
                    description=entry.get("description", ""),
                )
                leaves[node_id] = leaf
                bindings.append(VariantBinding(
                    variant_id=var_id,
                    router_id=router_id,
                    route_key_raw=route_key_raw,
                    base_message_id="",
                    leaf_node_id=node_id,
                ))
                continue

            # Base-message override pattern
            base_msg_id = entry.get("base_message", entry.get("base", ""))
            if not base_msg_id:
                continue

            # Find base leaf
            base_leaf = None
            for leaf in leaves.values():
                if leaf.message_ref == base_msg_id:
                    base_leaf = leaf
                    break

            if base_leaf is None:
                continue

            # Apply override fields
            override_fields = list(base_leaf.fields)
            for override in entry.get("override_fields", []):
                for i, f in enumerate(override_fields):
                    if f.name == override.get("name"):
                        override_fields[i] = FieldNode(
                            id=f"{node_id}.{override['name']}",
                            name=override["name"],
                            type_ref=override.get("type", f.type_ref),
                            params={
                                **f.params,
                                **{k: v for k, v in override.items()
                                   if k not in ("name", "type", "id")},
                            },
                            length=override.get("length", f.length),
                            default=override.get("default", f.default),
                        )
                        break

            variant_leaf = LeafNode(
                id=node_id,
                name=var_id,
                fields=tuple(override_fields),
                message_ref=base_msg_id,
                router_id=router_id,
                route_key=RouterBuilder.normalize_route_key(route_key_raw),
                description=entry.get("description", base_leaf.description),
            )
            leaves[node_id] = variant_leaf

            bindings.append(VariantBinding(
                variant_id=var_id,
                router_id=router_id,
                route_key_raw=route_key_raw,
                base_message_id=base_msg_id,
                leaf_node_id=node_id,
            ))

        return leaves, bindings


class RouterBuilder:
    """Helper for normalizing route keys. Shared with router_builder module."""

    @staticmethod
    def normalize_route_key(raw_keys: list[Any]) -> str:
        import json
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
                    # Keep hex-like strings as-is (e.g. DI codes like "00010000")
                    normalized.append(val.upper())
            else:
                normalized.append(val)

        if len(normalized) == 1 and isinstance(normalized[0], str):
            return normalized[0]
        return json.dumps(normalized, separators=(",", ":"))
