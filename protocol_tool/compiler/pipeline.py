"""Compilation pipeline — orchestrates the full YAML → IR compilation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from protocol_tool.ir.nodes import ProtocolIR, BuildPlan


def compile_protocol(
    registry_path: str | Path,
    protocol_name: str,
    *,
    output_dir: str | Path | None = None,
    protocols_dir: str | Path | None = None,
) -> ProtocolIR:
    """Compile a single protocol from YAML to ProtocolIR.

    This is the main entry point for the compiler.

    Parameters
    ----------
    registry_path:
        Path to the registry.yaml file.
    protocol_name:
        Protocol identifier to compile, e.g. "dlt645_2007".
    output_dir:
        If provided, write the compiled IR to <output_dir>/<protocol_name>.ir.json.
    protocols_dir:
        Directory containing protocol packages. Inferred from registry_path if None.

    Returns
    -------
    Compiled ProtocolIR.
    """
    from protocol_tool.compiler.loader import load_protocol
    from protocol_tool.compiler.resolver import Resolver
    from protocol_tool.compiler.frame_compiler import FrameCompiler
    from protocol_tool.compiler.message_compiler import MessageCompiler
    from protocol_tool.compiler.variant_compiler import VariantCompiler
    from protocol_tool.compiler.router_builder import RouterBuilder
    from protocol_tool.compiler.validator import Validator

    # Step 1: Load all YAML files
    unit = load_protocol(registry_path, protocol_name, protocols_dir=protocols_dir)
    if unit is None:
        raise ValueError(f"Protocol {protocol_name!r} not found in registry {registry_path}")

    # Step 2: Create resolver
    resolver = Resolver(unit)

    # Step 3: Compile frame
    frame_compiler = FrameCompiler(unit, resolver)
    frame = frame_compiler.compile()

    # Step 4: Compile messages (→ LeafNodes + MessageBindings)
    msg_compiler = MessageCompiler(unit, resolver, frame_compiler)
    leaves, msg_bindings = msg_compiler.compile()

    # Step 5: Compile variants (→ modified LeafNodes + VariantBindings)
    var_compiler = VariantCompiler(unit, resolver, frame_compiler)
    all_leaves, var_bindings = var_compiler.compile(leaves)

    # Step 6: Build routers
    router_builder = RouterBuilder(unit)
    all_bindings = list(msg_bindings) + list(var_bindings)
    # Convert VariantBinding to compatible type for router_builder
    routers = router_builder.build(msg_bindings, var_bindings)

    # Step 7: Build build plans (for each message, record the route chain)
    build_plans = _build_build_plans(
        protocol_name, msg_bindings, var_bindings, routers
    )

    # Step 8: Assemble ProtocolIR
    protocol_data = unit.protocol_data
    ir = ProtocolIR(
        version=1,
        protocol=protocol_name,
        name=protocol_data.get("name", protocol_name),
        frame=frame,
        routers=routers,
        leaves=all_leaves,
        build_plans=build_plans,
        algorithms={},  # Algorithms are in the codec registry, not in IR
        metadata={
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            "source_files": unit.source_files,
        },
    )

    # Step 9: Validate
    validator = Validator()
    issues = validator.validate(ir)
    if issues:
        raise ValueError(
            f"Validation failed for protocol {protocol_name!r}:\n" +
            "\n".join(f"  - {i}" for i in issues)
        )

    # Step 10: Write output
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{protocol_name}.ir.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ir.to_json())
        print(f"Compiled {protocol_name} → {output_path}")

    return ir


def _build_build_plans(
    protocol_name: str,
    msg_bindings: list,
    var_bindings: list,
    routers: dict,
) -> dict:
    """Build BuildPlan entries for each message."""
    from protocol_tool.ir.nodes import BuildPlan

    plans: dict[str, BuildPlan] = {}

    for b in msg_bindings:
        key_str = ""
        router_node = routers.get(b.router_id)
        if router_node:
            for k, v in router_node.route_table.items():
                if v == b.leaf_node_id:
                    key_str = k
                    break

        plans[b.message_id] = BuildPlan(
            message_id=b.message_id,
            route_chain=((b.router_id, key_str),) if key_str else (),
        )

    return plans
