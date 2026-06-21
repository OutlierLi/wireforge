"""Route graph visualization — generates DOT/SVG for protocol routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import ProtocolIR


def generate_dot(ir: ProtocolIR) -> str:
    """Generate a Graphviz DOT representation of the protocol route graph.

    Node shapes:
    - Ellipse: Frame / Entry
    - Rectangle: Struct / Message / Variant (LeafNodes)
    - Diamond: Router
    - Dashed box: Fallback / Raw Remaining
    """
    lines = ["digraph protocol_routes {", '  rankdir=TB;', '  node [fontname="monospace"];']
    node_id = 0

    def new_id():
        nonlocal node_id
        node_id += 1
        return f"n{node_id}"

    # Frame node (ellipse)
    frame_id = new_id()
    lines.append(
        f'  {frame_id} [label="Frame\\n{ir.protocol}", shape=ellipse, '
        f'style=filled, fillcolor=lightyellow];'
    )

    # Frame fields
    prev_id = frame_id
    for field in ir.frame.fields:
        fid = new_id()
        if field.type_ref == "routed_payload":
            lines.append(
                f'  {fid} [label="{field.name}\\n(routed)", shape=box, '
                f'style=filled, fillcolor=lightblue];'
            )
            # Connect to router
            router_id_s = field.params.get("router", "")
            if router_id_s in ir.routers:
                router_node = ir.routers[router_id_s]
                rid = _emit_router(router_node, ir, lines, new_id)
                lines.append(f"  {fid} -> {rid} [style=dashed, label=\"dispatch\"];")
        elif field.type_ref in ("sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            lines.append(
                f'  {fid} [label="{field.name}\\n({field.type_ref})", shape=hexagon];'
            )
        else:
            lines.append(f'  {fid} [label="{field.name}\\n({field.type_ref})", shape=box];')
        lines.append(f"  {prev_id} -> {fid};")
        prev_id = fid

    lines.append("}")
    return "\n".join(lines)


def _emit_router(router_node, ir, lines, new_id) -> str:
    """Emit a router and its route table as graph nodes."""
    rid = new_id()
    lines.append(
        f'  {rid} [label="Router\\n{router_node.id}\\nkeys: {list(router_node.key_paths)}", '
        f'shape=diamond, style=filled, fillcolor=lightgreen];'
    )

    for key_str, target_id in router_node.route_table.items():
        tid = new_id()
        leaf = ir.leaves.get(target_id)
        label = leaf.name if leaf else target_id
        field_count = len(leaf.fields) if leaf else 0
        lines.append(
            f'  {tid} [label="{label}\\n({field_count} fields)", shape=box, '
            f'style=filled, fillcolor=lightcyan];'
        )
        lines.append(f'  {rid} -> {tid} [label="{key_str}"];')

    # Fallback
    if router_node.fallback_policy != "error":
        fid = new_id()
        lines.append(
            f'  {fid} [label="fallback\\n{router_node.fallback_policy}", '
            f'shape=box, style=dashed];'
        )
        lines.append(f"  {rid} -> {fid} [style=dashed];")

    return rid
