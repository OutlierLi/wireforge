"""C struct intermediate layer for protocol extension."""

from protocol_extend.c_struct.builder import build_spec_from_c_struct, load_c_struct_source
from protocol_extend.c_struct.from_yaml import render_c_struct_source, slug_from_variant_id, struct_name_from_variant_id
from protocol_extend.c_struct.manifest import VariantManifest, VariantManifestEntry, build_variant_dict, render_variant_yaml
from protocol_extend.c_struct.parser import parse_c_struct
from protocol_extend.c_struct.to_yaml import c_struct_to_yaml_fields
from protocol_extend.c_struct.validator import validate_c_struct

__all__ = [
    "VariantManifest",
    "VariantManifestEntry",
    "build_spec_from_c_struct",
    "build_variant_dict",
    "c_struct_to_yaml_fields",
    "load_c_struct_source",
    "parse_c_struct",
    "render_c_struct_source",
    "render_variant_yaml",
    "slug_from_variant_id",
    "struct_name_from_variant_id",
    "validate_c_struct",
]
