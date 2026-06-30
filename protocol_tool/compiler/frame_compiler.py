"""Frame compiler — frame.yaml → FrameNode."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.ir.nodes import (
    FrameNode,
    FieldNode,
    TransformSpec,
    ConditionSpec,
)

if TYPE_CHECKING:
    from protocol_tool.compiler.loader import CompilationUnit
    from protocol_tool.compiler.resolver import Resolver


class FrameCompiler:
    """Compiles frame.yaml into a FrameNode."""

    def __init__(self, unit: CompilationUnit, resolver: Resolver) -> None:
        self.unit = unit
        self.resolver = resolver

    def compile(self) -> FrameNode:
        """Compile the frame definition from frame.yaml."""
        frame_data = self.unit.frame_data
        frame_id = frame_data.get("id", f"{self.unit.protocol_name}.frame")

        # Determine if frame has a "fields" key or uses inline field list
        if "fields" in frame_data:
            field_list = frame_data["fields"]
        else:
            # Bare frame YAML — the frame_data IS the field list
            field_list = frame_data.get("frame", frame_data).get("fields", [])

        fields = self._compile_fields(field_list, prefix=frame_id)
        return FrameNode(id=frame_id, fields=tuple(fields))

    def _compile_fields(
        self,
        field_list: list[dict[str, Any]],
        prefix: str = "",
    ) -> list[FieldNode]:
        """Compile a list of field YAML dicts into FieldNodes."""
        nodes: list[FieldNode] = []
        for i, item in enumerate(field_list):
            node = self._compile_field(item, i, prefix)
            nodes.append(node)
        return nodes

    def _compile_field(
        self,
        item: dict[str, Any],
        index: int,
        prefix: str,
    ) -> FieldNode:
        """Compile a single field YAML dict into a FieldNode."""
        item = self._resolve_field_yaml(dict(item))
        name = item["name"]
        type_ref = item["type"]

        fid = item.get("id", f"{prefix}.{name}")

        # Build params
        params = self.resolver.resolve_field_params(item)

        # Handle bitset sub-fields
        if type_ref == "bitset" and "bits" in item:
            params["bits"] = item["bits"]

        # Handle nested fields for struct/array (already domain-resolved)
        if "fields" in item:
            params["fields"] = item["fields"]

        # Resolve length
        length, length_from, length_adjust = self.resolver.resolve_length(item)

        # Handle transforms
        transforms: list[TransformSpec] = []
        transform_cfg = item.get("transform") or item.get("transforms")
        if transform_cfg:
            if isinstance(transform_cfg, dict):
                # Check for {decode: [...], encode: [...]} format
                if "decode" in transform_cfg or "encode" in transform_cfg:
                    decode_list = transform_cfg.get("decode", [])
                    if isinstance(decode_list, list):
                        for t in decode_list:
                            transforms.append(self._compile_transform(t))
                    else:
                        transforms.append(self._compile_transform(decode_list))
                elif "algorithm" in transform_cfg:
                    # Single transform: {algorithm: "sub_33h"}
                    transforms.append(self._compile_transform(transform_cfg))
            elif isinstance(transform_cfg, list):
                for t in transform_cfg:
                    transforms.append(self._compile_transform(t))

        # Handle condition
        condition = None
        if "when" in item or "condition" in item:
            cond_cfg = item.get("when") or item.get("condition")
            condition = self._compile_condition(cond_cfg)

        return FieldNode(
            id=fid,
            name=name,
            type_ref=type_ref,
            params=params,
            length=length,
            length_from=length_from,
            length_adjust=length_adjust,
            transforms=tuple(transforms),
            condition=condition,
            default=item.get("default"),
            optional=item.get("optional", False),
        )

    def _resolve_field_yaml(self, item: dict[str, Any]) -> dict[str, Any]:
        """Resolve domain types recursively (struct sub-fields, array item_params)."""
        item = dict(item)
        type_ref = str(item.get("type", "uint8"))
        type_def = self.resolver.resolve_field_type(type_ref)
        if type_def.get("type") != type_ref:
            base_type = type_def.get("type", type_ref)
            item = {
                **{k: v for k, v in type_def.items() if k != "type"},
                **item,
                "type": base_type,
            }
            type_ref = str(item["type"])

        if type_ref == "struct" and item.get("fields"):
            item["fields"] = [
                self._resolve_field_yaml(sf) for sf in item["fields"]
            ]

        if type_ref == "array":
            item_type_name = str(item.get("item_type") or "")
            item_params = dict(item.get("item_params") or {})
            if item_type_name == "struct":
                if item_params.get("fields"):
                    item_params["fields"] = [
                        self._resolve_field_yaml(sf) for sf in item_params["fields"]
                    ]
                item["item_params"] = item_params
            elif item_type_name:
                item_def = self.resolver.resolve_field_type(item_type_name)
                if item_def.get("type") != item_type_name:
                    base_item = item_def.get("type", item_type_name)
                    item["item_type"] = base_item
                    item["item_params"] = {
                        **{k: v for k, v in item_def.items() if k != "type"},
                        **item_params,
                    }

        return item

    @staticmethod
    def _compile_transform(cfg: dict[str, Any]) -> TransformSpec:
        """Compile a transform from YAML dict."""
        return TransformSpec(
            algorithm=cfg.get("algorithm", cfg.get("type", "")),
            params={k: v for k, v in cfg.items() if k not in ("algorithm", "type")},
        )

    @staticmethod
    def _compile_condition(cfg: dict[str, Any]) -> ConditionSpec | None:
        """Compile a condition spec from YAML dict."""
        if not cfg:
            return None
        return ConditionSpec(
            kind=cfg.get("kind", "equals"),
            field_ref=cfg.get("field_ref", cfg.get("field", "")),
            value=cfg.get("value"),
        )
