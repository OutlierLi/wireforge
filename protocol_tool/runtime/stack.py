"""ExecutionStack — tracks nested structure decoding during runtime.

When a routed_payload triggers a router and descends into a LeafNode,
a new StackFrame is pushed. When the LeafNode finishes, the frame is popped.
This allows nested routers to access fields from parent frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StackFrame:
    """One level of the execution stack.

    Parameters
    ----------
    node_id:
        The IR node currently being executed.
    scope_name:
        A label for this scope (e.g. "data_unit[0]" for repeat items).
    values:
        Field values parsed within this frame's scope.
    raw_sections:
        Raw byte sections accumulated in this frame.
    """

    node_id: str
    scope_name: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    raw_sections: dict[str, bytes] = field(default_factory=dict)

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
                raise KeyError(f"Path {path!r} not found in stack frame (missing {part!r})")
        return current


@dataclass
class ExecutionStack:
    """Tracks the stack of active decode frames.

    The root frame always exists (node_id="frame").
    Additional frames are pushed/popped as routers descend into sub-nodes.
    """

    frames: list[StackFrame] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.frames:
            self.frames.append(StackFrame(node_id="frame", scope_name="frame"))

    @property
    def current(self) -> StackFrame:
        """The topmost (current) stack frame."""
        return self.frames[-1]

    @property
    def root(self) -> StackFrame:
        """The root (bottom) stack frame."""
        return self.frames[0]

    def push(self, node_id: str, scope_name: str = "") -> StackFrame:
        """Push a new frame and return it."""
        frame = StackFrame(node_id=node_id, scope_name=scope_name)
        self.frames.append(frame)
        return frame

    def pop(self) -> StackFrame:
        """Pop and return the current frame. Cannot pop the root frame."""
        if len(self.frames) <= 1:
            raise IndexError("Cannot pop the root stack frame")
        return self.frames.pop()

    def depth(self) -> int:
        """Current stack depth (root = 1)."""
        return len(self.frames)

    # -- Cross-frame value lookup --

    def resolve(self, path: str) -> Any:
        """Resolve a dotted path by searching from current frame upward.

        First tries the current frame's values, then the parent's, etc.
        """
        # Try current frame first
        try:
            return self.current.get(path)
        except KeyError:
            pass
        # Walk up through parent frames
        for frame in reversed(self.frames[:-1]):
            try:
                return frame.get(path)
            except KeyError:
                continue
        raise KeyError(f"Path {path!r} not found in any stack frame")

    def set_current(self, path: str, value: Any) -> None:
        """Set a value in the current frame."""
        self.current.set(path, value)
