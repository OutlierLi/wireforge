"""DecodeContext and BuildContext — value accumulation during parse/build."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    """A single step in a decode trace."""

    node_id: str
    field_name: str
    field_type: str
    position: int  # byte offset in the buffer before reading this field
    raw_bytes: bytes | None = None
    decoded_value: Any = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "node": self.node_id,
            "field": self.field_name,
            "type": self.field_type,
            "position": self.position,
        }
        if self.raw_bytes is not None:
            d["raw"] = self.raw_bytes.hex(" ").upper()
        if self.decoded_value is not None:
            d["value"] = self.decoded_value
        if self.message:
            d["message"] = self.message
        return d


@dataclass
class DecodeContext:
    """Accumulates parsed field values and metadata during decode.

    Parameters
    ----------
    values:
        Flat namespace of parsed field values. Nested struct fields are stored
        with dotted keys, e.g. "control.func".
    trace:
        Ordered list of TraceEvents capturing each decode step.
    warnings:
        Non-fatal warnings encountered during decode.
    raw_sections:
        Raw byte sections accumulated for checksum computation.
        Keyed by field name.
    """

    values: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_sections: dict[str, bytes] = field(default_factory=dict)

    def set(self, path: str, value: Any) -> None:
        """Set a value at a dotted path.

        Simple dotted keys like "control.func" are stored flat:
        values["control.func"] = value.
        """
        self.values[path] = value

    def get(self, path: str) -> Any:
        """Get a value by dotted path.

        Looks up flat key first, then tries nested dict lookup.
        """
        if path in self.values:
            return self.values[path]

        # Nested lookup: "control.func" → values["control"]["func"]
        parts = path.split(".")
        current: Any = self.values
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise KeyError(f"Path {path!r} not found in context (missing {part!r})")
        return current

    def require(self, path: str) -> Any:
        """Get a value, raising KeyError with context if not found."""
        try:
            return self.get(path)
        except KeyError:
            available = sorted(self.values.keys())
            raise KeyError(
                f"Required path {path!r} not found. Available keys: {available}"
            )

    def add_trace(self, event: TraceEvent) -> None:
        """Record a trace event."""
        self.trace.append(event)

    def warning(self, message: str) -> None:
        """Record a non-fatal warning."""
        self.warnings.append(message)


@dataclass
class BuildContext:
    """Accumulates values and routing info during build.

    Parameters
    ----------
    values:
        Flat namespace of field values to encode (provided by caller).
    trace:
        Ordered list of TraceEvents capturing each encode step.
    raw_sections:
        Raw byte sections accumulated for checksum computation.
    route_chain:
        Explicit route chain guiding message/variant selection.
        Each entry is (router_id, route_key_str).
    message_id:
        The message being built (for LeafNode lookup).
    """

    values: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)
    raw_sections: dict[str, bytes] = field(default_factory=dict)
    route_chain: list[tuple[str, str]] = field(default_factory=list)
    message_id: str | None = None

    def set(self, path: str, value: Any) -> None:
        self.values[path] = value

    def get(self, path: str) -> Any:
        if path in self.values:
            return self.values[path]
        parts = path.split(".")
        current: Any = self.values
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise KeyError(f"Path {path!r} not found (missing {part!r})")
        return current

    def add_trace(self, event: TraceEvent) -> None:
        self.trace.append(event)
