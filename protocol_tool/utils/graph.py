"""Route graph — 从 IR 路由表直接生成 DOT/SVG，不模拟随机帧。

遍历路由树：frame → routers → leaves，生成有向图。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import ProtocolIR


# ── DOT 生成 ────────────────────────────────────────────────────────────

def generate_dot(ir: ProtocolIR) -> str:
    """从 IR 路由表直接生成 DOT 图。"""
    lines = [
        "digraph protocol_routes {",
        '  rankdir=TB; fontname="Helvetica"; bgcolor=white;',
        '  node [fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=9];',
        '  splines=polyline; nodesep=0.5; ranksep=0.6;',
        "",
    ]

    nid = [0]

    def next_id():
        nid[0] += 1
        return f"n{nid[0]}"

    nodes: dict[str, str] = {}

    def node(label: str, shape="box", color="", fontsize=10, penwidth=1) -> str:
        if label in nodes:
            return nodes[label]
        nd = next_id()
        attrs = [f'label="{label}"', f"shape={shape}", f"fontsize={fontsize}"]
        if color:
            attrs.append(f'style=filled,fillcolor="{color}"')
        if penwidth != 1:
            attrs.append(f"penwidth={penwidth}")
        lines.append(f"  {nd} [{', '.join(attrs)}];")
        nodes[label] = nd
        return nd

    def edge(src: str, dst: str, label="", style="solid", color="black"):
        attrs = []
        if label:
            attrs.append(f'label="{label}"')
        if style != "solid":
            attrs.append(f"style={style}")
        if color != "black":
            attrs.append(f"color={color}")
        lines.append(f"  {src} -> {dst}{' [' + ', '.join(attrs) + ']' if attrs else ''};")

    # ── 帧头 ──
    frame_id = node(f"{ir.name}\\n({ir.protocol})", "box", "lightyellow", 12, 2)

    # ── 帧字段链 ──
    prev = frame_id
    for field in ir.frame.fields:
        t = field.type_ref
        if t == "routed_payload":
            fid = node(f"{field.name}", "box", "lightblue")
            edge(prev, fid)
            prev = fid
        elif t in ("const", "const_repeat"):
            val = field.params.get("value", "?")
            fid = node(f"{field.name}=0x{val:02X}", "box", "#EEEEEE")
            edge(prev, fid)
            prev = fid
        elif "checksum" in t or t in ("sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            fid = node(f"{field.name}", "hexagon", "lightyellow")
            edge(prev, fid)
            prev = fid
        else:
            fid = node(f"{field.name}", "box", "")
            edge(prev, fid)
            prev = fid

    # ── 找帧级路由入口 ──
    frame_router_id = None
    for field in ir.frame.fields:
        if field.type_ref == "routed_payload":
            frame_router_id = field.params.get("router", "")
            break

    if not frame_router_id or frame_router_id not in ir.routers:
        lines.append("}")
        return "\n".join(lines)

    # ── 递归绘制路由树 ──
    trigger_node = nodes.get(next(
        (f"{f.name}" for f in ir.frame.fields if f.type_ref == "routed_payload"), ""))

    _emit_router(ir, frame_router_id, trigger_node, nodes, lines, nid, next_id)

    lines.append("}")
    return "\n".join(lines)


def _emit_router(ir, router_id: str, parent_node: str,
                 nodes: dict, lines: list, nid: list, next_id):
    rnode = ir.routers.get(router_id)
    if not rnode:
        return

    kn = ", ".join(rnode.key_paths)
    rid = next_id()
    lines.append(
        f'  {rid} [label="Router: {router_id}\\n[{kn}]", shape=diamond, '
        f'style=filled,fillcolor="lightgreen",fontsize=9];'
    )
    if parent_node:
        lines.append(f'  {parent_node} -> {rid} [style=dashed,color=blue,fontsize=8];')

    for key_str, target_id in sorted(rnode.route_table.items()):
        leaf = ir.leaves.get(target_id)
        if not leaf:
            continue

        # 格式化路由键
        try:
            vals = json.loads(key_str)
        except (json.JSONDecodeError, TypeError):
            vals = [key_str]
        if not isinstance(vals, list):
            vals = [vals]
        key_paths = rnode.key_paths
        label_parts = []
        for i, kp in enumerate(key_paths):
            if i < len(vals):
                v = vals[i]
                short = kp.split(".")[-1]
                label_parts.append(f"{short}={_fmt(v)}")
        edge_label = "\\n".join(label_parts) if label_parts else key_str

        # 检查叶子是否有子路由
        has_sub = False
        for f in leaf.fields:
            if f.type_ref == "routed_payload":
                sub_rid = f.params.get("router", "")
                if sub_rid in ir.routers:
                    # 叶子是中间节点 → 用 box
                    lid = next_id()
                    lines.append(
                        f'  {lid} [label="{leaf.name}", shape=box, '
                        f'style=filled,fillcolor="lightcyan",fontsize=8];'
                    )
                    lines.append(f'  {rid} -> {lid} [label="{edge_label}",fontsize=8];')
                    _emit_router(ir, sub_rid, lid, nodes, lines, nid, next_id)
                    has_sub = True
        if has_sub:
            continue

        # 终端叶子
        lid = next_id()
        fields_str = ", ".join(_leaf_field_names(leaf))
        label = leaf.name
        if fields_str:
            label += f"\\n[{fields_str}]"
        lines.append(
            f'  {lid} [label="{label}", shape=box, '
            f'style=filled,fillcolor="lightcyan",fontsize=8];'
        )
        lines.append(f'  {rid} -> {lid} [label="{edge_label}",fontsize=8];')


def _fmt(val) -> str:
    if isinstance(val, int):
        return f"0x{val:02X}"
    return str(val)


def _leaf_field_names(leaf) -> list[str]:
    names = []
    for lf in leaf.fields:
        t = lf.type_ref
        if t in ("const", "const_repeat", "checksum", "sum8", "xor8",
                 "crc16_modbus", "crc16_ccitt", "crc8"):
            continue
        if t == "routed_payload":
            continue
        if t == "struct":
            for sf in lf.params.get("fields", []):
                names.append(f"{lf.name}.{sf['name']}")
        else:
            names.append(lf.name)
    return names


# ── 渲染 ────────────────────────────────────────────────────────────────

def render_svg(dot_source: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".dot", delete=False, mode="w") as f:
        f.write(dot_source)
        dot_path = f.name
    try:
        return subprocess.run(["dot", "-Tsvg", dot_path], capture_output=True, check=True).stdout
    finally:
        Path(dot_path).unlink(missing_ok=True)


def generate_svg(ir: ProtocolIR, output_path: str | Path | None = None) -> str:
    dot = generate_dot(ir)
    svg_bytes = render_svg(dot)
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(svg_bytes)
    return svg_bytes.decode("utf-8")
