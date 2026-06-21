"""Struct codec — nested structure with sub-fields."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from protocol_tool.codecs.base import FieldCodec

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import FieldNode
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext


class StructCodec(FieldCodec):
    """Decodes/encodes a nested structure with sub-fields.

    The struct codec itself doesn't consume bytes directly.
    Instead, it iterates over its sub-fields (stored in field.params["fields"])
    and delegates to the appropriate codec for each.

    Parameters (from FieldNode.params):
        fields: list of FieldNode dicts that make up the struct
    """

    codec_registry = None  # Set by engine to share the same registry

    def decode(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> dict[str, Any]:
        from protocol_tool.codecs import CodecRegistry

        sub_fields_raw = field.params.get("fields", [])
        sub_fields = _normalize_fields(sub_fields_raw, f"{field.id}.")

        result: dict[str, Any] = {}
        for sub_field in sub_fields:
            # Check condition
            if sub_field.condition is not None:
                if not _eval_condition(sub_field.condition, context):
                    continue

            codec = _get_codec(sub_field.type_ref)
            value = codec.decode(sub_field, reader, context)

            # Store with dotted path relative to parent
            context.set(sub_field.id, value)
            result[sub_field.name] = value

        return result

    def encode(
        self,
        field: FieldNode,
        value: Any,
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        sub_fields_raw = field.params.get("fields", [])
        sub_fields = _normalize_fields(sub_fields_raw, f"{field.id}.")

        for sub_field in sub_fields:
            if sub_field.condition is not None:
                if not _eval_condition(sub_field.condition, context):
                    continue

            sub_value = _resolve_value(value, sub_field.name, sub_field.default)
            codec = _get_codec(sub_field.type_ref)
            codec.encode(sub_field, sub_value, writer, context)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_fields(raw: list[dict[str, Any]], prefix: str) -> list[FieldNode]:
    """Convert raw field dicts to FieldNode instances."""
    from protocol_tool.ir.nodes import FieldNode

    nodes: list[FieldNode] = []
    for i, item in enumerate(raw):
        fid = item.get("id", f"{prefix}field_{i}")
        nodes.append(FieldNode(
            id=fid,
            name=item["name"],
            type_ref=item["type"],
            params={k: v for k, v in item.items() if k not in ("name", "type", "id")},
            length=item.get("length"),
            length_from=item.get("length_from"),
            length_adjust=item.get("length_adjust", 0),
        ))
    return nodes


def _get_codec(type_ref: str):
    """Get a codec from the shared registry (set by engine), or fallback."""
    from protocol_tool.codecs.struct_codec import StructCodec
    if StructCodec.codec_registry is not None:
        return StructCodec.codec_registry.get(type_ref)
    # Fallback: create standalone registry
    if not hasattr(_get_codec, "_registry"):
        from protocol_tool.codecs import create_builtin_registry
        _get_codec._registry = create_builtin_registry()
    return _get_codec._registry.get(type_ref)


def _eval_condition(condition, context) -> bool:
    """Evaluate a ConditionSpec against the current context."""
    try:
        field_val = context.get(condition.field_ref)
    except KeyError:
        return False

    if condition.kind == "equals":
        return field_val == condition.value
    elif condition.kind == "not_equals":
        return field_val != condition.value
    elif condition.kind == "exists":
        return field_val is not None
    elif condition.kind == "bit_set":
        if isinstance(field_val, int) and isinstance(condition.value, int):
            return bool(field_val & condition.value)
        return False
    return True


def _resolve_value(source: Any, name: str, default: Any) -> Any:
    """Resolve a sub-field's value from a dict or object."""
    if isinstance(source, dict):
        return source.get(name, default)
    if hasattr(source, name):
        return getattr(source, name, default)
    return default
