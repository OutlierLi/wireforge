"""Route graph visualization from actual decode traces.

Builds real frames for every message/variant, decodes them, and captures
the actual routing path taken — showing concrete key values in hex on edges.
"""

from __future__ import annotations

import json
import random
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from protocol_tool.ir.nodes import ProtocolIR

NOW = datetime.now()


# ── Manual frame builders (mirrors roundtrip test) ────────────────────

def _random_addr() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(12))






# ── Route collection via decode trace ─────────────────────────────────

def collect_routes(ir: ProtocolIR) -> list[dict[str, Any]]:
    """Build frames for all messages and variants, decode, capture route decisions.

    Returns list of route entries: {router_id, key_paths, keys, target, hex_label}
    """
    from protocol_tool.codecs import create_builtin_registry
    from protocol_tool.runtime.engine import DecodeEngine
    from protocol_tool.codecs.routed import RoutedPayloadCodec

    codecs = create_builtin_registry()
    engine = DecodeEngine(ir, codecs)
    routed_codec = codecs.get("routed_payload")
    if not isinstance(routed_codec, RoutedPayloadCodec):
        return []

    routes: list[dict] = []
    seen: set[str] = set()
    addr = _random_addr()

    # Hook the routed_payload codec to intercept route decisions
    orig_decode = routed_codec.decode

    def hook_decode(field, reader, context):
        router_id = field.params.get("router", "")
        router_node = ir.routers.get(router_id) if router_id else None

        if router_node:
            from protocol_tool.runtime.router import Router
            router = Router(router_node)
            try:
                keys = []
                for path in router_node.key_paths:
                    try:
                        keys.append((path, context.get(path)))
                    except KeyError:
                        keys.append((path, None))

                target_id = router.resolve(context)
                target_name = ""
                if target_id and target_id in ir.leaves:
                    target_name = ir.leaves[target_id].name

                ns = f"{router_id}:{json.dumps(keys)}"
                if ns not in seen:
                    seen.add(ns)
                    routes.append({
                        "router_id": router_id,
                        "key_paths": list(router_node.key_paths),
                        "keys": keys,
                        "target": target_id,
                        "target_name": target_name,
                        "fallback": router_node.fallback_policy,
                    })
            except Exception:
                pass

        return orig_decode(field, reader, context)

    routed_codec.decode = hook_decode

    try:
        _trace_all(ir, engine, routed_codec)
    finally:
        routed_codec.decode = orig_decode

    return routes


def _trace_all(ir, engine, routed_codec):
    """Exercise every variant by building proper frames from the IR route tables."""
    import random
    from datetime import datetime
    now = datetime.now()

    # Walk router tree generically for all protocols
    frame_router_id = None
    for field in ir.frame.fields:
        if field.type_ref == "routed_payload":
            frame_router_id = field.params.get("router", "")
            break

    if not frame_router_id or frame_router_id not in ir.routers:
        return

    # Collect the frame bytes for a given route path
    def make_frame(route_path):
        """Build a minimal frame from route values — generic, no protocol hardcoding."""
        return _make_trace_frame(ir, route_path)

    # Walk all sub-routers and build frames
    _walk_routers(ir, engine, frame_router_id, {}, make_frame)


def _walk_routers(ir, engine, router_id, parent_vals, make_frame, depth=0):
    """Recursively walk router tree, building and decoding frames for each route."""
    if depth > 5:
        return
    rnode = ir.routers.get(router_id)
    if not rnode:
        return

    for key_str, target_id in rnode.route_table.items():
        leaf = ir.leaves.get(target_id)
        if not leaf:
            continue

        # Build route path so far
        route_vals = dict(parent_vals)
        # Parse key values back from serialized form
        import json
        try:
            key_vals = json.loads(key_str)
        except (json.JSONDecodeError, TypeError):
            key_vals = [key_str]
        if not isinstance(key_vals, list):
            key_vals = [key_vals]

        for i, path in enumerate(rnode.key_paths):
            if i < len(key_vals):
                route_vals[path] = key_vals[i]

        # Build and decode a frame — route_vals already encodes all branching
        frame = make_frame(route_vals)
        if frame:
            try:
                engine.decode(frame)
            except Exception:
                pass

        # Recurse into sub-routers
        for field in leaf.fields:
            if field.type_ref == "routed_payload":
                sub_router = field.params.get("router", "")
                if sub_router in ir.routers:
                    _walk_routers(ir, engine, sub_router, route_vals, make_frame, depth + 1)


def _make_trace_frame(ir, route_vals):
    """Build a minimal frame by walking IR frame fields generically.

    Zero protocol-specific code — all behavior driven by FrameNode field definitions.
    """
    import random, json

    rv = {}  # flattened: "control.func" → "func"
    for k, v in route_vals.items():
        rv[k.split(".", 1)[-1]] = v

    raw = {}   # field_name → bytes (populated in first pass)
    order = [] # field_names in order

    # ── Pass 1: build every field's bytes ──
    for field in ir.frame.fields:
        t, n = field.type_ref, field.name
        order.append(n)

        if t == "const_repeat":
            v = field.params.get("value", 0)
            if isinstance(v, str): v = int(v.replace("0x", "").replace("0X", ""), 16)
            raw[n] = bytes([v])

        elif t == "const":
            v = field.params.get("value", 0)
            if isinstance(v, str): v = int(v.replace("0x", "").replace("0X", ""), 16)
            raw[n] = bytes([v])

        elif t == "bcd":
            nbytes = field.length or 6
            digits = "".join(str(random.randint(0, 9)) for _ in range(nbytes * 2))
            b = bytes((int(digits[i], 16) << 4) | int(digits[i+1], 16) for i in range(0, len(digits), 2))
            if field.params.get("byte_order", "") in ("little", "reverse"):
                b = b[::-1]
            raw[n] = b

        elif t in ("uint8", "uint16_le", "uint16_be", "uint24_le", "uint32_le", "uint32_be", "uint48_le"):
            width = { "uint8": 1, "uint16_le": 2, "uint16_be": 2, "uint24_le": 3,
                      "uint32_le": 4, "uint32_be": 4, "uint48_le": 6 }.get(t, 1)
            raw[n] = bytes([0] * width)  # placeholder; Pass 2 fixes length refs

        elif t in ("hex", "bytes"):
            raw[n] = bytes([0] * (field.length or 4))

        elif t == "bitset":
            val = 0
            for bs in field.params.get("bits", []):
                bn = bs["name"]
                bv = rv.get(bn, bs.get("default", 0))
                if "bit" in bs:
                    val |= (int(bv) & 1) << bs["bit"]
                elif "offset" in bs:
                    mask = (1 << bs.get("width", 1)) - 1
                    val |= (int(bv) & mask) << bs["offset"]
            raw[n] = bytes([val])

        elif t == "routed_payload":
            router_id = field.params.get("router", "")
            raw[n] = _build_minimal_body(ir, router_id, rv, field.transforms)

        elif "checksum" in t or t in ("sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            raw[n] = b""  # placeholder

        else:
            raw[n] = bytes([0])

    # ── Pass 2: fix auto-computed fields (length, checksum) ──
    # First, handle length_from references: if field F has length_from=X, set X=len(F)+adjust
    for field in ir.frame.fields:
        if field.length_from and field.length_from in raw:
            # Decode: this field reads (ref_value + adjust) bytes
            # Encode: ref_value = len(this_field) - adjust
            raw[field.length_from] = (len(raw[field.name]) - field.length_adjust).to_bytes(
                len(raw[field.length_from]), 'little')

    total_frame_len = sum(len(raw.get(f.name, b"")) for f in ir.frame.fields)

    for field in ir.frame.fields:
        t, n = field.type_ref, field.name

        # Auto-compute uint length fields not already fixed by length_from
        if t.startswith("uint"):
            if n not in raw or len(raw[n]) == 0:
                raw[n] = bytes([0] * {"uint8":1,"uint16_le":2,"uint16_be":2}.get(t,1))
            # If still placeholder (all zeros), fill with total_frame_len
            if raw[n] == bytes([0] * len(raw[n])) and not field.length_from:
                raw[n] = total_frame_len.to_bytes(len(raw[n]), 'little')

        # Checksum
        if "checksum" in t or t in ("sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8"):
            cover = field.params.get("cover", [])
            cover_data = b"".join(raw.get(c, b"") for c in cover if c in raw)
            raw[n] = bytes([sum(cover_data) & 0xFF])

    # ── Assemble ──
    return b"".join(raw[n] for n in order if n in raw)


def _build_minimal_body(ir, router_id, rv, transforms=()):
    """Recursively build minimal body bytes for a routed_payload from IR router tree."""
    import json
    if not router_id or router_id not in ir.routers:
        return bytes([0x00])

    rnode = ir.routers[router_id]
    keys = []
    for path in rnode.key_paths:
        keys.append(rv.get(path.split(".", 1)[-1], 0))

    if len(keys) == 1 and isinstance(keys[0], str):
        key_str = keys[0]
    elif len(keys) == 1:
        key_str = json.dumps(keys)
    else:
        key_str = json.dumps(keys, separators=(",", ":"))

    target_id = rnode.route_table.get(key_str)
    if not target_id or target_id not in ir.leaves:
        return bytes([0x00])

    leaf = ir.leaves[target_id]
    body = bytearray()

    for lf in leaf.fields:
        if lf.optional:
            continue
        t = lf.type_ref
        if t == "routed_payload":
            body.extend(_build_minimal_body(ir, lf.params.get("router", ""), rv))
        elif t == "uint8":
            v = rv.get(lf.name, 0)
            body.append(int(v) if isinstance(v, (int, str)) else 0)
        elif t == "enum":
            v = rv.get(lf.name, 0)
            body.append(int(v) if isinstance(v, int) else 0)
        elif t == "bcd":
            v = rv.get(lf.name, "")
            if isinstance(v, str) and v:
                digits = v.zfill((lf.length or 1) * 2)
                b = bytes((int(digits[i], 16) << 4) | int(digits[i+1], 16) for i in range(0, len(digits), 2))
                if lf.params.get("byte_order", "") in ("little", "reverse"):
                    b = b[::-1]
                body.extend(b)
            else:
                body.extend(bytes([0] * (lf.length or 1)))
        elif t in ("hex", "bytes"):
            v = rv.get(lf.name, "")
            if isinstance(v, str) and v:
                v_clean = v.replace(" ", "")
                b = bytes.fromhex(v_clean)
                if lf.params.get("byte_order", "") in ("little", "reverse"):
                    b = b[::-1]
                body.extend(b)
            else:
                body.extend(bytes([0] * (lf.length or 1)))
        elif t == "struct":
            for sf in lf.params.get("fields", []):
                st = sf.get("type", "uint8")
                sv = rv.get(sf.get("name", ""), 0)
                if isinstance(sv, int):
                    body.extend(sv.to_bytes(sf.get("length", 1), 'big'))
                else:
                    body.extend(bytes([0] * sf.get("length", 1)))
        else:
            body.append(0)

    # Apply wire transforms if any (e.g. DLT645 +33H)
    for xf in transforms:
        if xf.algorithm == "add_33h":
            body = bytearray((b + 0x33) & 0xFF for b in body)
        elif xf.algorithm == "sub_33h":
            body = bytearray((b - 0x33) & 0xFF for b in body)

    return bytes(body)



# ── DOT generation ────────────────────────────────────────────────────

def generate_dot(ir: ProtocolIR, routes: list[dict] | None = None) -> str:
    """Generate DOT from collected route traces."""
    if routes is None:
        routes = collect_routes(ir)

    lines = [
        "digraph protocol_routes {",
        '  rankdir=TB;',
        '  fontname="Helvetica";',
        '  node [fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=9];',
        '  bgcolor=white;',
        '  splines=polyline;',
        '  nodesep=0.6;',
        '  ranksep=0.7;',
        "",
    ]

    nid = [0]
    def nid_next(): nid[0] += 1; return f"n{nid[0]}"

    node_map: dict[str, str] = {}

    def node(label: str, shape="box", fillcolor="", extra="") -> str:
        if label in node_map:
            return node_map[label]
        nd = nid_next()
        style = f'style=filled,fillcolor="{fillcolor}",' if fillcolor else ""
        lines.append(f'  {nd} [label="{label}", shape={shape}, {style}{extra}];')
        node_map[label] = nd
        return nd

    # ── Frame header ──
    fid = node(f"{ir.protocol}\\n{ir.name}", "box", "lightyellow", "fontsize=12,penwidth=2")
    prev = fid

    # ── Frame fields ──
    for field in ir.frame.fields:
        if field.type_ref == "routed_payload":
            fid = node(f"{field.name}\\n(routed_payload)", "box", "lightblue")
            lines.append(f"  {prev} -> {fid};")
            prev = fid
        elif field.type_ref in ("const", "const_repeat"):
            val = field.params.get("value", "?")
            fid = node(f"{field.name}=0x{val:02X}", "box", "#EEEEEE")
            lines.append(f"  {prev} -> {fid};")
            prev = fid
        elif "checksum" in field.type_ref or field.type_ref in (
            "sum8", "xor8", "crc16_modbus", "crc16_ccitt", "crc8",
        ):
            fid = node(f"{field.name}\\n({field.type_ref})", "hexagon", "lightyellow")
            lines.append(f"  {prev} -> {fid};")
            prev = fid
        else:
            fid = node(f"{field.name}\\n({field.type_ref})", "box", "")
            lines.append(f"  {prev} -> {fid};")
            prev = fid

    # ── Routers from ACTUAL runtime traces only ──
    router_routes: dict[str, list[dict]] = {}
    for r in (routes or []):
        router_routes.setdefault(r["router_id"], []).append(r)

    for router_id, entries in router_routes.items():
        rnode = ir.routers.get(router_id)
        if not rnode:
            continue
        kn = ", ".join(rnode.key_paths)
        rid = node(f"Router: {router_id}\\n[{kn}]", "diamond", "lightgreen", "fontsize=9")

        # Connect from trigger field in frame
        for field in ir.frame.fields:
            if field.type_ref == "routed_payload" and field.params.get("router") == router_id:
                trigger_n = node_map.get(f"{field.name}\\n(routed_payload)")
                if trigger_n:
                    lines.append(f'  {trigger_n} -> {rid} [style=dashed,color=blue,label="dispatch",fontsize=8];')
                break

        # Draw routes from trace
        seen_t: dict[str, list[str]] = {}
        for e in entries:
            tgt = e.get("target_name") or e.get("target") or "?"
            parts = []
            for p, v in e.get("keys", []):
                if isinstance(v, int): parts.append(f"{p}=0x{v:02X}")
                elif isinstance(v, str): parts.append(f"{p}={v}")
                else: parts.append(f"{p}={v}")
            seen_t.setdefault(tgt, []).append("\\n".join(parts))

        for tgt, labels in seen_t.items():
            tid = node(tgt, "box", "lightcyan", "fontsize=7")
            lbl = labels[0].replace('"', "'")
            lines.append(f'  {rid} -> {tid} [label="{lbl}",fontsize=8];')

        # Fallback
        if rnode.fallback_policy != "error":
            fid = node(f"fallback\\n({rnode.fallback_policy})", "box", "", "style=dashed,fontsize=8")
            lines.append(f"  {rid} -> {fid} [style=dashed,color=gray];")

    # ── Connect leaves to their sub-routers ──
    for leaf_id, leaf in ir.leaves.items():
        for field in leaf.fields:
            if field.type_ref == "routed_payload":
                sr = field.params.get("router", "")
                if sr not in ir.routers:
                    continue
                srn = ir.routers[sr]
                sr_kn = ", ".join(srn.key_paths)
                sr_label = f"Router: {sr}\\n[{sr_kn}]"
                if sr_label not in node_map:
                    # Sub-router not in graph yet (no routes collected) — emit it anyway
                    srid = nid_next()
                    lines.append(
                        f'  {srid} [label="Router: {sr}\\n[{sr_kn}]", shape=diamond, '
                        f'style=filled,fillcolor="lightgreen",fontsize=9];'
                    )
                    node_map[sr_label] = srid
                    # Emit routes for this sub-router too
                    for key_str, target_id in sorted(srn.route_table.items()):
                        tleaf = ir.leaves.get(target_id)
                        tname = tleaf.name if tleaf else target_id
                        tid = node(tname, "box", "lightcyan", "fontsize=7")
                        lines.append(f'  {srid} -> {tid} [label="{key_str}",fontsize=8];')
                # Connect leaf to sub-router
                leaf_n = node_map.get(leaf.name)
                sub_n = node_map.get(sr_label)
                if leaf_n and sub_n:
                    lines.append(f'  {leaf_n} -> {sub_n} '
                                 f'[style=dashed,color=blue,label="dispatch",fontsize=8];')

    lines.append("}")
    return "\n".join(lines)


# ── Rendering ─────────────────────────────────────────────────────────

def render_svg(dot_source: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".dot", delete=False, mode="w") as f:
        f.write(dot_source)
        dot_path = f.name
    try:
        return subprocess.run(
            ["dot", "-Tsvg", dot_path], capture_output=True, check=True
        ).stdout
    finally:
        Path(dot_path).unlink(missing_ok=True)


def render_png(dot_source: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".dot", delete=False, mode="w") as f:
        f.write(dot_source)
        dot_path = f.name
    try:
        return subprocess.run(
            ["dot", "-Tpng", dot_path], capture_output=True, check=True
        ).stdout
    finally:
        Path(dot_path).unlink(missing_ok=True)


def generate_svg(ir: ProtocolIR, output_path: str | Path | None = None) -> str:
    routes = collect_routes(ir)
    dot = generate_dot(ir, routes)
    svg_bytes = render_svg(dot)
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(svg_bytes)
    return svg_bytes.decode("utf-8")
