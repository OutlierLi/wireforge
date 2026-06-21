"""Runtime execution engine.

The runtime loads a compiled ProtocolIR and executes decode/build operations.
It is protocol-agnostic — all protocol-specific behavior is defined in the IR.
"""

from protocol_tool.runtime.reader import DecodeReader, BufferOverrunError
from protocol_tool.runtime.context import (
    DecodeContext,
    BuildContext,
    TraceEvent,
)
from protocol_tool.runtime.stack import ExecutionStack, StackFrame
from protocol_tool.runtime.router import Router, RouteError
from protocol_tool.runtime.engine import DecodeEngine, BuildEngine

__all__ = [
    "DecodeReader",
    "BufferOverrunError",
    "DecodeContext",
    "BuildContext",
    "TraceEvent",
    "ExecutionStack",
    "StackFrame",
    "Router",
    "RouteError",
    "DecodeEngine",
    "BuildEngine",
]
