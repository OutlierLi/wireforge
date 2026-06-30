"""YAML loader — discovers and loads protocol YAML files.

Entry point: load_protocol(registry_path, protocol_name) → CompilationUnit
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CompilationUnit:
    """All YAML data for one protocol, loaded and ready for compilation."""

    protocol_name: str
    protocol_root: Path

    # YAML contents
    registry_data: dict[str, Any] = field(default_factory=dict)
    protocol_data: dict[str, Any] = field(default_factory=dict)
    frame_data: dict[str, Any] = field(default_factory=dict)
    types_data: dict[str, dict[str, Any]] = field(default_factory=dict)  # type_name → type_def
    message_data: list[dict[str, Any]] = field(default_factory=list)
    variant_data: list[dict[str, Any]] = field(default_factory=list)

    # Source map (for error messages and metadata)
    source_files: dict[str, str] = field(default_factory=dict)


def load_protocol(
    registry_path: str | Path,
    protocol_name: str,
    *,
    protocols_dir: str | Path | None = None,
) -> CompilationUnit | None:
    """Load all YAML files for a named protocol.

    Parameters
    ----------
    registry_path:
        Path to the registry.yaml file.
    protocol_name:
        Protocol identifier, e.g. "dlt645_2007".
    protocols_dir:
        Directory containing protocol packages. If None, inferred from registry_path.

    Returns
    -------
    CompilationUnit or None if the protocol is not found in the registry.
    """
    from protocol_tool.utils.yaml_loader import load_yaml, glob_yaml

    registry_path = Path(registry_path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Registry file not found: {registry_path}")

    registry = load_yaml(registry_path)
    if registry is None:
        raise ValueError(f"Empty registry: {registry_path}")

    # Resolve protocol root
    if protocols_dir is None:
        protocols_dir = registry_path.parent

    protocols_dir = Path(protocols_dir)

    # Find protocol entry in registry
    proto_entry = None
    for entry in registry.get("protocols", []):
        if isinstance(entry, dict):
            if entry.get("id") == protocol_name:
                proto_entry = entry
                break

    if proto_entry is None:
        return None

    package = proto_entry.get("package", "")
    # package points to protocol.yaml within the protocol directory
    # e.g. "dlt645_2007/protocol.yaml" → root = "dlt645_2007/"
    proto_yaml_path = protocols_dir / package
    proto_root = proto_yaml_path.parent
    if not proto_yaml_path.exists():
        raise FileNotFoundError(
            f"Protocol package not found for {protocol_name!r}: "
            f"{proto_yaml_path} (from package={package!r})"
        )

    unit = CompilationUnit(
        protocol_name=protocol_name,
        protocol_root=proto_root,
        registry_data=registry,
    )

    # Load protocol.yaml
    unit.protocol_data = load_yaml(proto_yaml_path)
    unit.source_files["protocol.yaml"] = str(proto_yaml_path)

    # Load frame.yaml
    frame_ref = unit.protocol_data.get("frame_ref", "frame.yaml")
    frame_path = proto_root / frame_ref
    if frame_path.exists():
        unit.frame_data = load_yaml(frame_path)
        unit.source_files["frame.yaml"] = str(frame_path)

    # Load types/*.yaml
    types_dir = proto_root / "types"
    for yaml_path in glob_yaml(types_dir, "*.yaml"):
        data = load_yaml(yaml_path)
        if data:
            for type_name, type_def in data.items():
                unit.types_data[type_name] = type_def
            unit.source_files[f"types/{yaml_path.name}"] = str(yaml_path)

    # Load types from protocol.yaml sources
    type_sources = unit.protocol_data.get("sources", {}).get("types", "")
    if type_sources:
        for yaml_path in glob_yaml(proto_root, type_sources):
            data = load_yaml(yaml_path)
            if data:
                for type_name, type_def in data.items():
                    unit.types_data[type_name] = type_def
                rel = str(yaml_path.relative_to(proto_root))
                unit.source_files[rel] = str(yaml_path)

    # Load messages/*.yaml
    msg_sources = unit.protocol_data.get("sources", {}).get("messages", "messages/**/*.yaml")
    for yaml_path in glob_yaml(proto_root, msg_sources):
        data = load_yaml(yaml_path)
        if data:
            unit.message_data.append(data)
            rel = str(yaml_path.relative_to(proto_root))
            unit.source_files[rel] = str(yaml_path)

    # Load variants/*.yaml
    var_sources = unit.protocol_data.get("sources", {}).get("variants", "variants/**/*.yaml")
    if isinstance(var_sources, list):
        for pattern in var_sources:
            for yaml_path in glob_yaml(proto_root, pattern):
                data = load_yaml(yaml_path)
                if data:
                    unit.variant_data.append(data)
                    rel = str(yaml_path.relative_to(proto_root))
                    unit.source_files[rel] = str(yaml_path)
    else:
        for yaml_path in glob_yaml(proto_root, var_sources):
            data = load_yaml(yaml_path)
            if data:
                unit.variant_data.append(data)
                rel = str(yaml_path.relative_to(proto_root))
                unit.source_files[rel] = str(yaml_path)

    return unit
