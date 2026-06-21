"""Resolver — resolves $ref, type references, and cross-file references."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.compiler.loader import CompilationUnit


class Resolver:
    """Resolves references within a CompilationUnit.

    Handles:
    - Type references: when a field has type="energy_4", resolve it from types_data.
    - $ref references: when a field references another YAML file.
    - length_ref / count_ref: references to other field names.
    """

    def __init__(self, unit: CompilationUnit) -> None:
        self.unit = unit

    def resolve_field_type(self, type_name: str) -> dict[str, Any]:
        """Resolve a type name to its full definition.

        If type_name is a built-in (uint8, bcd, etc.), return it as-is.
        If type_name is in types_data, return the resolved definition.
        """
        # Built-in types
        builtins = {
            "uint8", "uint16_le", "uint16_be", "uint24_le", "uint24_be",
            "uint32_le", "uint32_be", "uint48_le", "uint48_be",
            "bcd", "bcd_numeric", "bitset", "const", "const_repeat",
            "routed_payload", "checksum", "hex", "bytes", "ascii",
            "struct", "array", "enum",
            "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8",
        }
        if type_name in builtins:
            return {"type": type_name}

        # Domain-specific types from types/*.yaml
        if type_name in self.unit.types_data:
            return self.unit.types_data[type_name]

        # Not found in types — it's probably a built-in codec name
        return {"type": type_name}

    def resolve_field_params(self, field_yaml: dict[str, Any]) -> dict[str, Any]:
        """Extract codec parameters from a field YAML definition.

        Separates: name, type, id from the params dict.
        Everything else becomes codec params.
        """
        params: dict[str, Any] = {}
        skip_keys = {"name", "type", "id", "fields", "bits"}
        for key, value in field_yaml.items():
            if key not in skip_keys:
                params[key] = value
        return params

    def resolve_length(self, field_yaml: dict[str, Any]) -> tuple[int | None, str | None, int]:
        """Resolve length specification from a field YAML.

        Returns (length, length_from, length_adjust).
        """
        length = field_yaml.get("length")
        length_from = field_yaml.get("length_from")
        length_adjust = field_yaml.get("length_adjust", 0)

        if isinstance(length, int):
            return length, None, 0
        if isinstance(length, str) and length.startswith("ref:"):
            return None, length[4:], length_adjust
        if length_from is not None:
            return None, length_from, length_adjust
        return length, None, 0
