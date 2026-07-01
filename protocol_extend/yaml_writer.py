"""Generate extension variant YAML and write to variants/extensions/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXTENSIONS_DIR = ROOT / "protocol_tool" / "protocols" / "csg_2016" / "variants" / "extensions"

# Backward compat for tests monkeypatching CSG path.
EXTENSIONS_DIR = DEFAULT_EXTENSIONS_DIR


from protocol_extend.fields import FIELD_DSL_EXAMPLES, missing_field_metadata  # noqa: F401


def _is_yaml_ready_field(field: dict[str, Any]) -> bool:
    if "type" not in field or "name" not in field:
        return False
    agent_markers = ("evidence", "bytes", "item_fields", "semantic_override")
    return not any(key in field for key in agent_markers)


from protocol_extend.fields import field_to_yaml as _field_to_yaml


def _body_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not fields:
        return []
    return [
        f if _is_yaml_ready_field(f) else _field_to_yaml(f)
        for f in fields
    ]


def build_variants(spec: ExtensionSpec) -> list[dict[str, Any]]:
    return spec.profile.build_variants(spec)


def extension_filename(spec: ExtensionSpec) -> str:
    return spec.profile.extension_filename(spec)


def render_extension_yaml(spec: ExtensionSpec, raw_input: str) -> str:
    return spec.profile.render_extension_yaml(spec, raw_input)


def write_extension_file(spec: ExtensionSpec, raw_input: str, extensions_dir: Path | None = None) -> Path:
    target_dir = extensions_dir or spec.profile.extensions_dir(ROOT)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = extension_filename(spec)
    path = target_dir / filename
    if path.exists():
        raise FileExistsError(f"extension file already exists: {path}")
    path.write_text(render_extension_yaml(spec, raw_input), encoding="utf-8")
    return path
