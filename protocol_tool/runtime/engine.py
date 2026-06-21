"""DecodeEngine and BuildEngine — the runtime heart of the system.

These engines walk the ProtocolIR frame fields, dispatching each to the
appropriate codec. They are protocol-agnostic — all protocol-specific behavior
comes from the IR and the codec registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import (
        ProtocolIR,
        FieldNode,
        LeafNode,
        RouterNode,
    )
    from protocol_tool.runtime.reader import DecodeReader
    from protocol_tool.runtime.context import DecodeContext, BuildContext
    from protocol_tool.codecs import CodecRegistry


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DecodeResult:
    """Output of a decode operation."""

    protocol: str
    values: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_hex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "values": self.values,
            "warnings": self.warnings,
            "raw_hex": self.raw_hex,
            "trace": self.trace,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass
class BuildResult:
    """Output of a build operation."""

    protocol: str
    frame: bytes = b""
    frame_hex: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    parsed: dict[str, Any] | None = None  # Optional round-trip validation

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "frame_hex": self.frame_hex,
            "frame_length": len(self.frame),
            "trace": self.trace,
        }


# ---------------------------------------------------------------------------
# DecodeEngine
# ---------------------------------------------------------------------------

class DecodeEngine:
    """Walks ProtocolIR frame fields and decodes raw bytes.

    Usage:
        ir = ProtocolIR.from_json_file("dlt645_2007.ir.json")
        registry = create_builtin_registry()
        engine = DecodeEngine(ir, registry)
        result = engine.decode(frame_bytes)
    """

    def __init__(self, ir: ProtocolIR, codec_registry: CodecRegistry) -> None:
        self.ir = ir
        self.codecs = codec_registry

        # Wire up RoutedPayloadCodec with engine reference
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        routed = self.codecs.get("routed_payload")
        if isinstance(routed, RoutedPayloadCodec):
            routed.set_engine(self, ir)

    # -- Public API --

    def decode(self, data: bytes) -> DecodeResult:
        """Decode raw bytes into a DecodeResult."""
        from protocol_tool.runtime.reader import DecodeReader
        from protocol_tool.runtime.context import DecodeContext
        from protocol_tool.runtime.stack import ExecutionStack

        reader = DecodeReader(data, 0, len(data))
        context = DecodeContext()
        stack = ExecutionStack()

        # Walk frame fields in order
        for field in self.ir.frame.fields:
            self._decode_field(field, reader, context, stack)

        return DecodeResult(
            protocol=self.ir.protocol,
            values=context.values,
            trace=[e.to_dict() for e in context.trace],
            warnings=context.warnings,
            raw_hex=data.hex(" ").upper(),
        )

    def decode_hex(self, hex_text: str) -> DecodeResult:
        """Decode a hex string."""
        cleaned = hex_text.strip().replace(" ", "").replace("\n", "")
        return self.decode(bytes.fromhex(cleaned))

    def decode_with_trace(self, data: bytes) -> DecodeResult:
        """Decode and return detailed trace (same as decode — trace is always collected)."""
        return self.decode(data)

    # -- Internal field dispatch --

    def _decode_field(
        self,
        field: FieldNode,
        reader: DecodeReader,
        context: DecodeContext,
        stack,
    ) -> None:
        """Decode a single field: get codec, call decode, record trace."""
        from protocol_tool.runtime.context import TraceEvent

        pos_before = reader.tell()

        # Check condition
        if field.condition is not None:
            if not self._eval_condition(field.condition, context):
                context.add_trace(TraceEvent(
                    node_id=stack.current.node_id,
                    field_name=field.name,
                    field_type=field.type_ref,
                    position=pos_before,
                    message="skipped (condition false)",
                ))
                return

        # Resolve codec
        try:
            codec = self.codecs.get(field.type_ref)
        except KeyError:
            context.warning(f"Unknown codec {field.type_ref!r} for field {field.name!r}, skipping")
            length = self._resolve_field_length(field, context)
            if length is not None and length > 0:
                reader.read(length)
            return

        # Determine raw byte range before decode (for checksum accumulation)
        raw_len = self._resolve_field_length(field, context)
        if raw_len is None and field.type_ref not in ("routed_payload", "const_repeat"):
            raw_len = 1  # Default for fixed-length fields

        # Decode
        raw_start = reader.tell()
        try:
            value = codec.decode(field, reader, context)
        except Exception as exc:
            raise DecodeError(
                f"Failed to decode field {field.name!r} (type={field.type_ref}) "
                f"at offset {pos_before}: {exc}"
            ) from exc
        raw_end = reader.tell()

        # Save raw bytes for checksum computation
        raw_bytes = reader.data[raw_start:raw_end]
        if raw_bytes:
            context.raw_sections[field.name] = raw_bytes

        # Store value
        context.set(field.name, value)

        # Record trace
        raw_len = reader.tell() - pos_before
        context.add_trace(TraceEvent(
            node_id=stack.current.node_id,
            field_name=field.name,
            field_type=field.type_ref,
            position=pos_before,
            raw_bytes=reader.data[pos_before:pos_before + raw_len] if raw_len > 0 else None,
            decoded_value=value,
        ))

    def _decode_leaf(
        self,
        leaf_id: str,
        reader: DecodeReader,
        context: DecodeContext,
    ) -> dict[str, Any]:
        """Decode a leaf node's fields. Called by RoutedPayloadCodec."""
        from protocol_tool.runtime.stack import ExecutionStack
        from protocol_tool.runtime.context import DecodeContext as DC

        leaf = self.ir.leaves.get(leaf_id)
        if leaf is None:
            context.warning(f"Unknown leaf node: {leaf_id!r}")
            return {"_raw": reader.read_remaining()}

        # Use a sub-stack for the leaf scope
        sub_context = DC(
            values={},
            trace=context.trace,  # Share trace
            warnings=context.warnings,  # Share warnings
            raw_sections=context.raw_sections,  # Share raw sections for checksum
        )

        for field in leaf.fields:
            self._decode_field(field, reader, sub_context, ExecutionStack())

        # Merge leaf values into parent context (namespaced)
        result: dict[str, Any] = {}
        for key, val in sub_context.values.items():
            context.set(f"{leaf.name}.{key}", val)
            result[key] = val
        return result

    # -- Helpers --

    @staticmethod
    def _resolve_field_length(
        field: FieldNode,
        context: DecodeContext,
    ) -> int | None:
        if field.length is not None:
            return field.length
        if field.length_from is not None:
            val = context.values.get(field.length_from)
            if val is not None and isinstance(val, int):
                return val + field.length_adjust
        return None

    @staticmethod
    def _eval_condition(condition, context: DecodeContext) -> bool:
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


class DecodeError(ValueError):
    """Raised when a decode step fails."""
    pass


# ---------------------------------------------------------------------------
# BuildEngine
# ---------------------------------------------------------------------------

class BuildEngine:
    """Walks ProtocolIR frame fields and constructs bytes from values.

    Usage:
        ir = ProtocolIR.from_json_file("dlt645_2007.ir.json")
        registry = create_builtin_registry()
        engine = BuildEngine(ir, registry)
        result = engine.build({"control": {"func": 17, "dir": 1}, ...}, message_id="read_data_response")
    """

    def __init__(self, ir: ProtocolIR, codec_registry: CodecRegistry) -> None:
        self.ir = ir
        self.codecs = codec_registry

        # Wire up RoutedPayloadCodec
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        routed = self.codecs.get("routed_payload")
        if isinstance(routed, RoutedPayloadCodec):
            routed.set_engine(self, ir)

    # -- Public API --

    def build(self, values: dict[str, Any], *, message_id: str | None = None) -> BuildResult:
        """Build a frame from field values.

        Parameters
        ----------
        values:
            Field values to encode. Can include nested dicts for struct fields.
        message_id:
            Optional message ID for routed payload dispatch.
            If not provided, attempts to resolve from values.
        """
        from protocol_tool.codecs.base import ByteWriter
        from protocol_tool.runtime.context import BuildContext

        writer = ByteWriter()
        context = BuildContext(
            values=values,
            message_id=message_id,
        )

        # Walk frame fields in order
        for field in self.ir.frame.fields:
            self._encode_field(field, values, writer, context)

        frame = writer.bytes()
        return BuildResult(
            protocol=self.ir.protocol,
            frame=frame,
            frame_hex=frame.hex(" ").upper(),
        )

    def build_hex(self, values: dict[str, Any], *, message_id: str | None = None) -> str:
        """Build and return hex string."""
        result = self.build(values, message_id=message_id)
        return result.frame_hex

    # -- Internal field dispatch --

    def _encode_field(
        self,
        field: FieldNode,
        values: dict[str, Any],
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        """Encode a single field."""
        from protocol_tool.runtime.context import TraceEvent

        # Check condition
        if field.condition is not None:
            if not self._eval_condition(field.condition, context):
                context.add_trace(TraceEvent(
                    node_id="frame",
                    field_name=field.name,
                    field_type=field.type_ref,
                    position=len(writer),
                    message="skipped (condition false)",
                ))
                return

        # Resolve field value
        field_value = values.get(field.name, field.default)
        if field_value is None and not field.optional:
            raise BuildError(
                f"Required field {field.name!r} not provided and has no default"
            )
        if field_value is None:
            return  # Skip optional field with no value

        # Resolve codec
        try:
            codec = self.codecs.get(field.type_ref)
        except KeyError:
            raise BuildError(f"Unknown codec {field.type_ref!r} for field {field.name!r}")

        # Encode
        pos_before = len(writer)
        try:
            codec.encode(field, field_value, writer, context)
        except Exception as exc:
            raise BuildError(
                f"Failed to encode field {field.name!r} (type={field.type_ref}): {exc}"
            ) from exc

        # Record trace
        context.add_trace(TraceEvent(
            node_id="frame",
            field_name=field.name,
            field_type=field.type_ref,
            position=pos_before,
            message=f"encoded {field_value!r}",
        ))

    def _encode_leaf(
        self,
        leaf: LeafNode,
        values: dict[str, Any],
        writer: ByteWriter,
        context: BuildContext,
    ) -> None:
        """Encode a leaf node's fields. Called by RoutedPayloadCodec."""
        sub_context = BuildContext(
            values=values,
            trace=context.trace,
            raw_sections=context.raw_sections,
            message_id=leaf.message_ref,
        )

        for field in leaf.fields:
            self._encode_field(field, values, writer, sub_context)

    @staticmethod
    def _eval_condition(condition, context: BuildContext) -> bool:
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


class BuildError(ValueError):
    """Raised when a build step fails."""
    pass
