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
    path_str: str = ""

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
    path: list[dict[str, Any]] | None = None   # Route path taken
    path_str: str = ""                          # Human-readable path
    parsed: dict[str, Any] | None = None

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

        # Share codec registry with StructCodec (so sub-fields use the same registry)
        from protocol_tool.codecs.struct_codec import StructCodec
        StructCodec.codec_registry = codec_registry

        # Wire up RoutedPayloadCodec with engine reference
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        routed = self.codecs.get("routed_payload")
        if isinstance(routed, RoutedPayloadCodec):
            routed.set_engine(self, ir)

    # -- Public API --

    def decode(self, data: bytes) -> DecodeResult:
        """Decode raw bytes into a DecodeResult."""
        # Re-bind RoutedPayloadCodec to this engine
        routed = self.codecs.get("routed_payload")
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        if isinstance(routed, RoutedPayloadCodec):
            routed.set_engine(self, self.ir)

        from protocol_tool.runtime.reader import DecodeReader
        from protocol_tool.runtime.context import DecodeContext
        from protocol_tool.runtime.stack import ExecutionStack

        # Collect route path during decode
        route_path = []
        routed = self.codecs.get("routed_payload")
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        orig_decode = None
        if isinstance(routed, RoutedPayloadCodec):
            orig_decode = routed.decode
            def hook_decode(field, reader, ctx):
                rid = field.params.get("router", "")
                rnode = self.ir.routers.get(rid) if rid else None
                if rnode:
                    from protocol_tool.runtime.router import Router
                    router = Router(rnode)
                    try:
                        keys = []
                        for p in rnode.key_paths:
                            try: keys.append((p, ctx.get(p)))
                            except KeyError: keys.append((p, None))
                        target = router.resolve(ctx)
                        tname = self.ir.leaves[target].name if target and target in self.ir.leaves else str(target)
                        route_path.append(f"{rid}[{_fmt_keys(keys)}]→{tname}")
                    except Exception:
                        pass
                return orig_decode(field, reader, ctx)
            routed.decode = hook_decode

        reader = DecodeReader(data, 0, len(data))
        context = DecodeContext()
        stack = ExecutionStack()

        try:
            for field in self.ir.frame.fields:
                self._decode_field(field, reader, context, stack)

            path_str = " → ".join(route_path)
            result = DecodeResult(
                protocol=self.ir.protocol,
                values=context.values,
                trace=[e.to_dict() for e in context.trace],
                warnings=context.warnings,
                raw_hex=data.hex(" ").upper(),
                path_str=path_str,
            )

            from protocol_tool.utils.logger import log_decode
            log_decode(
                protocol=self.ir.protocol,
                frame_hex=result.raw_hex,
                path=result.path_str,
                values=context.values,
                warnings=context.warnings,
            )
            return result
        except Exception as e:
            from protocol_tool.utils.logger import log_decode
            log_decode(
                protocol=self.ir.protocol,
                frame_hex=data.hex(" ").upper(),
                path=" → ".join(route_path),
                success=False,
                error=str(e),
            )
            raise
        finally:
            if orig_decode and isinstance(routed, RoutedPayloadCodec):
                routed.decode = orig_decode

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

        # Skip optional field if no bytes remain
        if field.optional and reader.exhausted():
            context.add_trace(TraceEvent(
                node_id=stack.current.node_id,
                field_name=field.name,
                field_type=field.type_ref,
                position=pos_before,
                message="skipped (optional, no bytes)",
            ))
            return

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

        # Use a sub-context that can see parent values (needed for conditions like control.add)
        sub_context = DC(
            values=dict(context.values),  # Inherit parent values for cross-layer field refs
            trace=context.trace,
            warnings=context.warnings,
            raw_sections=context.raw_sections,
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


def _fmt_keys(keys: list) -> str:
    """Format route keys for logging."""
    parts = []
    for p, v in keys:
        if isinstance(v, int):
            parts.append(f"{p}=0x{v:02X}")
        elif isinstance(v, str):
            parts.append(f"{p}={v}")
        else:
            parts.append(f"{p}={v}")
    return ", ".join(parts)


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

        # Share codec registry with StructCodec
        from protocol_tool.codecs.struct_codec import StructCodec
        StructCodec.codec_registry = codec_registry

        # Wire up RoutedPayloadCodec
        from protocol_tool.codecs.routed import RoutedPayloadCodec
        routed = self.codecs.get("routed_payload")
        if isinstance(routed, RoutedPayloadCodec):
            routed.set_engine(self, ir)

    # -- Public API --

    def resolve_path(self, info: dict[str, Any]) -> dict:
        """Given partial info (afn, di, direction, has_address...), find the
        complete route path from frame root to target leaf through all routers.

        Returns: {path, leaf_id, leaf_name, message_id, route_vals}
        Raises ValueError if no matching path found.
        """
        import json

        # Find the frame-level router
        frame_router_id = None
        for field in self.ir.frame.fields:
            if field.type_ref == "routed_payload":
                frame_router_id = field.params.get("router", "")
                break

        if not frame_router_id or frame_router_id not in self.ir.routers:
            raise ValueError("No frame-level router found")

        # Map direction words to values
        dir_val = None
        direction = info.get("direction", "")
        if direction == "downlink":  dir_val = 0
        elif direction == "uplink": dir_val = 1

        has_addr = info.get("has_address", False)
        add_val = 1 if has_addr else 0

        route_vals: dict[str, Any] = {}
        path_steps: list[dict] = []
        visited: set[str] = set()

        def _walk(router_id: str, depth: int = 0) -> bool:
            if depth > 10 or router_id in visited:
                return False
            visited.add(router_id)

            rnode = self.ir.routers.get(router_id)
            if not rnode:
                return False

            # Build candidate keys from info + current route_vals
            candidates: list[tuple[str, str]] = []  # (key_str, leaf_id)

            for key_str, target_id in rnode.route_table.items():
                # Parse key
                try:
                    key_vals = json.loads(key_str)
                except (json.JSONDecodeError, TypeError):
                    key_vals = [key_str]
                if not isinstance(key_vals, list):
                    key_vals = [key_vals]

                # Check if this key matches our info
                match = True
                for i, path in enumerate(rnode.key_paths):
                    if i >= len(key_vals):
                        match = False; break
                    want = key_vals[i]
                    short = path.split(".", 1)[-1]

                    # Check against explicit info
                    if short == "dir" and dir_val is not None and want != dir_val:
                        match = False; break
                    if short == "add" and add_val is not None and want != add_val:
                        match = False; break
                    if short == "afn" and "afn" in info and want != info["afn"]:
                        match = False; break
                    if short == "di" and "di" in info:
                        di_info = info["di"]
                        if isinstance(want, str) and isinstance(di_info, str):
                            if want.upper() != di_info.upper():
                                match = False; break
                        elif want != di_info:
                            match = False; break
                    if short == "func" and "func" in info and want != info["func"]:
                        match = False; break

                if match:
                    candidates.append((key_str, target_id))

            if not candidates:
                return False

            for key_str, target_id in candidates:
                leaf = self.ir.leaves.get(target_id)
                if not leaf:
                    continue

                # Record this step's key values
                try:
                    key_vals = json.loads(key_str)
                except (json.JSONDecodeError, TypeError):
                    key_vals = [key_str]
                if not isinstance(key_vals, list):
                    key_vals = [key_vals]

                saved = {}
                for i, path in enumerate(rnode.key_paths):
                    if i < len(key_vals):
                        route_vals[path] = key_vals[i]
                        saved[path] = key_vals[i]

                # Check if leaf is a terminal (has sub-router or is end)
                has_sub_router = any(
                    f.type_ref == "routed_payload" and f.params.get("router", "") in self.ir.routers
                    for f in leaf.fields
                )

                if has_sub_router:
                    # Recurse into sub-routers
                    for field in leaf.fields:
                        if field.type_ref == "routed_payload":
                            sub_router = field.params.get("router", "")
                            if sub_router in self.ir.routers:
                                if _walk(sub_router, depth + 1):
                                    path_steps.append({
                                        "router_id": router_id, "key_str": key_str,
                                        "leaf_id": target_id, "leaf_name": leaf.name,
                                    })
                                    return True
                    # Undo saved values if recursion failed
                    for p in saved:
                        route_vals.pop(p, None)
                else:
                    # Terminal leaf found
                    path_steps.append({
                        "router_id": router_id, "key_str": key_str,
                        "leaf_id": target_id, "leaf_name": leaf.name,
                    })
                    return True

            return False

        if not _walk(frame_router_id):
            raise ValueError(
                f"No route found for info={info}. "
                f"Check direction, afn, di, has_address values."
            )

        path_steps.reverse()
        terminal = path_steps[-1]

        return {
            "path": path_steps,
            "leaf_id": terminal["leaf_id"],
            "leaf_name": terminal["leaf_name"],
            "message_id": path_steps[0]["leaf_name"],  # first leaf is the frame-level message
            "route_vals": dict(route_vals),
            "path_str": " → ".join(
                f"{s['router_id']}[{s['key_str']}]→{s['leaf_name']}" for s in path_steps
            ),
        }

    def build(self, values: dict[str, Any], *,
              message_id: str | None = None,
              info: dict[str, Any] | None = None) -> BuildResult:
        path_info = None
        try:
            # Re-bind RoutedPayloadCodec to this engine
            routed = self.codecs.get("routed_payload")
            from protocol_tool.codecs.routed import RoutedPayloadCodec
            if isinstance(routed, RoutedPayloadCodec):
                routed.set_engine(self, self.ir)

            # Resolve path from info if no explicit message_id
            if info and not message_id:
                path_info = self.resolve_path(info)
                message_id = path_info["message_id"]
            # Merge route_vals into values so codecs can use them
            if path_info:
                for k, v in path_info["route_vals"].items():
                    if k not in values:
                        parts = k.split(".", 1)
                        if len(parts) == 2:
                            values.setdefault(parts[0], {})[parts[1]] = v
                        else:
                            values.setdefault(k, v)
        except Exception:
            pass  # path resolution may fail for optional nested routers

        from protocol_tool.codecs.base import ByteWriter
        from protocol_tool.runtime.context import BuildContext

        writer = ByteWriter()
        context = BuildContext(
            values=values,
            message_id=message_id,
        )

        # Pre-compute payload length (two-pass: encode just to measure, discard output)
        payload_len = {}
        for field in self.ir.frame.fields:
            if field.type_ref == "routed_payload":
                pre_writer = ByteWriter()
                pre_ctx = BuildContext(values=values, message_id=message_id)
                routed = self.codecs.get("routed_payload")
                if isinstance(routed, RoutedPayloadCodec):
                    routed.set_engine(self, self.ir)
                self._encode_field(field, values, pre_writer, pre_ctx)
                payload_len[field.name] = len(pre_writer)

        # Inject computed lengths
        for field in self.ir.frame.fields:
            if field.name in ("total_length", "length"):
                rp_name = "user_data" if "user_data" in payload_len else "data"
                plen = payload_len.get(rp_name, 0)
                if field.name == "total_length":
                    values["total_length"] = plen + 6
                elif field.name == "length":
                    values["length"] = plen
            self._encode_field(field, values, writer, context)

        frame = writer.bytes()
        result = BuildResult(
            protocol=self.ir.protocol,
            frame=frame,
            frame_hex=frame.hex(" ").upper(),
            path=path_info["path"] if path_info else None,
            path_str=path_info["path_str"] if path_info else "",
        )

        # 记录日志
        from protocol_tool.utils.logger import log_build
        log_build(
            protocol=self.ir.protocol,
            info=info,
            message_id=message_id,
            path=result.path_str,
            frame_hex=result.frame_hex,
            values=values,
        )
        return result

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
        # Auto-generated fields don't need user input
        auto_types = {"const", "const_repeat", "sum8", "xor8",
                      "crc16_modbus", "crc16_ccitt", "crc8", "routed_payload"}
        auto_names = {"total_length", "length"}  # frame-level computed fields
        if field.type_ref in auto_types or field.name in auto_names or field.optional:
            field_value = values.get(field.name) if values else None
            # Still encode even if None — codec auto-generates the value
        else:
            field_value = values.get(field.name, field.default)
            if field_value is None:
                raise BuildError(
                    f"Required field {field.name!r} not provided and has no default"
                )

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

        # Save raw bytes for checksum computation
        raw_bytes = writer.bytes()[pos_before:]
        if raw_bytes:
            context.raw_sections[field.name] = raw_bytes

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
        from protocol_tool.runtime.context import BuildContext as BC
        sub_context = BC(
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


def _compute_leaf_byte_length(leaf) -> int:
    """Compute total byte length of a leaf's fields (recursive for nested routed_payload)."""
    total = 0
    for f in leaf.fields:
        if f.optional:
            continue
        t = f.type_ref
        if t == "routed_payload":
            # Can't know without IR — return 0 for nested
            continue
        elif f.length is not None:
            total += f.length
        elif t == "uint8":
            total += 1
        elif t in ("uint16_le", "uint16_be"):
            total += 2
        elif t in ("uint24_le",):
            total += 3
        elif t in ("uint32_le", "uint32_be"):
            total += 4
        elif t in ("enum", "bitset"):
            total += f.length or 1
        elif t in ("hex", "bytes"):
            total += f.length or 1
        elif t == "bcd":
            total += f.length or 1
        elif t == "bcd_numeric":
            total += f.length or 1
        elif t == "ascii":
            total += f.length or 1
        elif t == "struct":
            for sf in f.params.get("fields", []):
                total += sf.get("length", 1)
        else:
            total += f.length or 1
    return total
