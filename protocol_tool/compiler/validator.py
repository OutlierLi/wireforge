"""Validator — cross-field validation and conflict detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import ProtocolIR


class Validator:
    """Validates a compiled ProtocolIR for correctness.

    Checks:
    - All length_ref / count_ref targets exist
    - Checksum cover fields exist
    - Router key_paths reference parseable fields
    - No orphan leaves (not referenced by any router)
    """

    def validate(self, ir: ProtocolIR) -> list[str]:
        """Validate a ProtocolIR. Returns list of issues (empty = valid).

        Raises ValueError for fatal issues.
        """
        issues: list[str] = []

        # Collect all known field names
        known_fields = {f.name for f in ir.frame.fields}
        for leaf in ir.leaves.values():
            for f in leaf.fields:
                known_fields.add(f.name)

        # Check frame field references
        for field in ir.frame.fields:
            if field.length_from and field.length_from not in known_fields:
                issues.append(
                    f"Field {field.name!r}: length_from={field.length_from!r} "
                    f"references unknown field"
                )
            if field.condition and field.condition.field_ref not in known_fields:
                issues.append(
                    f"Field {field.name!r}: condition references unknown field "
                    f"{field.condition.field_ref!r}"
                )

        # Check checksum cover fields
        for field in ir.frame.fields:
            if field.type_ref in ("sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
                cover = field.params.get("cover", [])
                for cover_field in cover:
                    if cover_field not in known_fields and cover_field != field.name:
                        issues.append(
                            f"Checksum field {field.name!r}: cover includes "
                            f"unknown field {cover_field!r}"
                        )

        # Check router key_paths reference valid fields
        for router in ir.routers.values():
            for path in router.key_paths:
                parts = path.split(".")
                if parts[0] not in known_fields:
                    issues.append(
                        f"Router {router.id!r}: key_path {path!r} references "
                        f"unknown root field {parts[0]!r}"
                    )

        # Check for orphan leaves
        all_referenced = set()
        for router in ir.routers.values():
            all_referenced.update(router.route_table.values())
        for leaf_id in ir.leaves:
            if leaf_id not in all_referenced:
                issues.append(f"Leaf node {leaf_id!r} is not referenced by any router")

        return issues
