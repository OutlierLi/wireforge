"""protocolctl — protocol compilation, decode, build, and inspection CLI.

Usage:
    protocolctl compile --protocol dlt645_2007
    protocolctl decode --protocol dlt645_2007 --hex "FE FE 68 ... 16"
    protocolctl build --protocol dlt645_2007 --message read_data_response --values '{"di": "00010000"}'
    protocolctl inspect routes --protocol dlt645_2007
    protocolctl inspect graph --protocol dlt645_2007
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="protocolctl",
    help="Protocol compilation, decode, build, and inspection tool",
    no_args_is_help=True,
)

# -- Shared options --

def _registry_path() -> Path:
    """Find the registry.yaml file."""
    # Try relative to current directory
    candidates = [
        Path("protocol_tool/protocols/registry.yaml"),
        Path("protocols/registry.yaml"),
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fallback
    return Path("protocol_tool/protocols/registry.yaml")


def _get_ir(protocol: str) -> "ProtocolIR":
    """Load a compiled ProtocolIR for a protocol.

    Tries compiled/<protocol>.ir.json first, then compiles from YAML.
    """
    from protocol_tool.ir.nodes import ProtocolIR

    # Try compiled cache
    compiled_path = Path(f"compiled/{protocol}.ir.json")
    if compiled_path.exists():
        return ProtocolIR.from_json_file(str(compiled_path))

    # Try to compile
    from protocol_tool.compiler.pipeline import compile_protocol
    registry = _registry_path()
    if not registry.exists():
        raise typer.BadParameter(
            f"Registry not found at {registry}. "
            f"Run 'protocolctl compile --protocol {protocol}' first."
        )
    ir = compile_protocol(str(registry), protocol, output_dir="compiled")
    return ir


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

@app.command()
def compile(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to compile"),
    registry: Optional[Path] = typer.Option(None, "--registry", help="Path to registry.yaml"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory for .ir.json"),
    force: bool = typer.Option(False, "--force", "-f", help="Force recompile even if cached"),
):
    """Compile a protocol from YAML definitions to IR JSON."""
    from protocol_tool.compiler.pipeline import compile_protocol

    registry_path = registry or _registry_path()
    if not registry_path.exists():
        typer.echo(f"Error: Registry not found at {registry_path}", err=True)
        raise typer.Exit(code=1)

    output_dir = output or Path("compiled")

    try:
        ir = compile_protocol(
            str(registry_path),
            protocol,
            output_dir=output_dir,
        )
        typer.echo(f"✓ Compiled {protocol}")
        typer.echo(f"  Frame fields: {len(ir.frame.fields)}")
        typer.echo(f"  Routers: {len(ir.routers)}")
        typer.echo(f"  Messages/Variants: {len(ir.leaves)}")
        typer.echo(f"  Output: {output_dir}/{protocol}.ir.json")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# decode
# ---------------------------------------------------------------------------

@app.command()
def decode(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to use"),
    hex_input: str = typer.Option(..., "--hex", help="Hex frame to decode"),
    trace: bool = typer.Option(False, "--trace", "-t", help="Show decode trace"),
    format: str = typer.Option("json", "--format", "-f", help="Output format: json, tree, yaml"),
):
    """Decode a protocol frame from hex bytes."""
    try:
        ir = _get_ir(protocol)
        from protocol_tool.codecs import create_builtin_registry
        from protocol_tool.runtime.engine import DecodeEngine
        from protocol_tool.utils.hex import normalize_hex

        registry = create_builtin_registry()
        engine = DecodeEngine(ir, registry)

        hex_clean = normalize_hex(hex_input)
        data = bytes.fromhex(hex_clean)
        result = engine.decode(data)

        if format == "json":
            import json
            typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        elif format == "tree":
            _print_tree(result)
        else:
            # yaml
            import yaml
            typer.echo(yaml.dump(result.to_dict(), allow_unicode=True, default_flow_style=False))

        if trace:
            typer.echo("\n── Trace ──")
            _print_trace(result)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

@app.command()
def build(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to use"),
    message: str = typer.Option(..., "--message", "-m", help="Message ID to build"),
    values: str = typer.Option("{}", "--values", "-v", help="JSON values for message fields"),
    format: str = typer.Option("hex", "--format", "-f", help="Output format: hex, json"),
):
    """Build a protocol frame from field values."""
    import json

    try:
        ir = _get_ir(protocol)
        from protocol_tool.codecs import create_builtin_registry
        from protocol_tool.runtime.engine import BuildEngine

        registry = create_builtin_registry()
        engine = BuildEngine(ir, registry)

        vals = json.loads(values)
        result = engine.build(vals, message_id=message)

        if format == "json":
            typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            typer.echo(result.frame_hex)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

inspect_app = typer.Typer(help="Inspect protocol IR")
app.add_typer(inspect_app, name="inspect")


@inspect_app.command("routes")
def inspect_routes(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to inspect"),
    router: Optional[str] = typer.Option(None, "--router", "-r", help="Filter by router ID"),
):
    """Show route tables for a protocol."""
    try:
        ir = _get_ir(protocol)

        routers = ir.routers
        if router:
            routers = {router: ir.routers[router]} if router in ir.routers else {}

        for router_id, router_node in routers.items():
            typer.echo(f"\nRouter: {router_id}")
            typer.echo(f"  Keys: {list(router_node.key_paths)}")
            typer.echo(f"  Fallback: {router_node.fallback_policy}")
            typer.echo(f"  Routes:")
            if not router_node.route_table:
                typer.echo("    (empty)")
            for key_str, target_id in router_node.route_table.items():
                leaf = ir.leaves.get(target_id)
                name = leaf.name if leaf else target_id
                typer.echo(f"    {key_str:30s} → {name}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@inspect_app.command("graph")
def inspect_graph(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to inspect"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output SVG path"),
):
    """Generate a route graph for a protocol."""
    try:
        ir = _get_ir(protocol)
        from protocol_tool.utils.graph import generate_dot

        dot = generate_dot(ir)
        typer.echo(dot)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(dot)
            typer.echo(f"\nGraph written to {output}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@inspect_app.command("protocol")
def inspect_protocol(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to inspect"),
):
    """Show protocol overview."""
    try:
        ir = _get_ir(protocol)
        typer.echo(f"Protocol: {ir.protocol}")
        typer.echo(f"Name: {ir.name}")
        typer.echo(f"IR Version: {ir.version}")
        typer.echo(f"Frame fields: {len(ir.frame.fields)}")
        for f in ir.frame.fields:
            typer.echo(f"  - {f.name}: {f.type_ref}")
        typer.echo(f"Routers: {len(ir.routers)}")
        for r in ir.routers.values():
            typer.echo(f"  - {r.id}: keys={list(r.key_paths)}, routes={len(r.route_table)}")
        typer.echo(f"Messages/Variants: {len(ir.leaves)}")
        for lid, leaf in ir.leaves.items():
            typer.echo(f"  - {lid}: {leaf.name} ({len(leaf.fields)} fields)")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

@app.command()
def test(
    protocol: str = typer.Option(..., "--protocol", "-p", help="Protocol to test"),
    filter_glob: Optional[str] = typer.Option(None, "--filter", help="Filter test cases by glob"),
):
    """Run protocol test cases (decode round-trip)."""
    typer.echo(f"Testing {protocol}...")
    typer.echo("(test cases defined in YAML — TBD)")
    # Future: load test cases from YAML and run decode→build→decode roundtrip


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_tree(result, indent: int = 0) -> None:
    """Print decode result as an indented tree."""
    prefix = "  " * indent
    for key, value in result.values.items():
        if isinstance(value, dict):
            typer.echo(f"{prefix}{key}:")
            _print_tree_values(value, indent + 1)
        elif isinstance(value, list):
            typer.echo(f"{prefix}{key}: [{len(value)} items]")
        else:
            typer.echo(f"{prefix}{key}: {value}")


def _print_tree_values(d: dict, indent: int) -> None:
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            typer.echo(f"{prefix}{k}:")
            _print_tree_values(v, indent + 1)
        elif isinstance(v, list):
            typer.echo(f"{prefix}{k}: [{len(v)} items]")
        else:
            typer.echo(f"{prefix}{k}: {v}")


def _print_trace(result) -> None:
    """Print decode trace events."""
    for i, event in enumerate(result.trace):
        pos = event.get("position", 0)
        field = event.get("field", "?")
        ftype = event.get("type", "?")
        msg = event.get("message", "")
        value = event.get("value")
        raw = event.get("raw", "")
        node = event.get("node", "")

        line = f"[{i}] {node} {field} ({ftype}) @{pos}"
        if raw:
            line += f" raw={raw}"
        if value is not None:
            line += f" → {value}"
        if msg:
            line += f" | {msg}"
        typer.echo(line)
