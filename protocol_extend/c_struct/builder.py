"""Build ExtensionSpec from C struct user_input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protocol_extend.c_struct.parser import parse_c_struct, read_c_struct_file
from protocol_extend.c_struct.to_yaml import c_struct_to_yaml_fields
from protocol_extend.c_struct.validator import validate_c_struct
from protocol_extend.parser import build_spec, merge_user_input
from protocol_extend.schema import ExtensionSpec, normalize_add

ROOT = Path(__file__).resolve().parent.parent.parent


def load_c_struct_source(
    user_input: dict[str, Any],
    inline_key: str,
    path_key: str,
    *,
    root: Path | None = None,
) -> tuple[str, str | None]:
    inline = user_input.get(inline_key)
    if inline not in (None, ""):
        return str(inline), None
    path_val = user_input.get(path_key)
    if path_val not in (None, ""):
        source, resolved = read_c_struct_file(str(path_val), root=root or ROOT)
        return source, resolved
    raise ValueError(f"{inline_key} or {path_key} is required")


def _apply_struct_metadata(spec: ExtensionSpec, metadata: object) -> None:
    if metadata.afn is not None and spec.afn is None:
        spec.afn = metadata.afn
    if metadata.di and not spec.di:
        spec.di = metadata.di
    if metadata.dir is not None and spec.dir is None:
        spec.dir = metadata.dir
    if metadata.add is not None and spec.add is None:
        spec.add = metadata.add
    if metadata.description and not spec.description:
        spec.description = metadata.description
    if metadata.pair:
        spec.pair = True
    if metadata.resp_description and not spec.resp_description:
        spec.resp_description = metadata.resp_description


def _parse_one_struct(source: str, *, path: str | None = None) -> tuple[list[dict[str, Any]], object]:
    defn = parse_c_struct(source, path=path)
    validate_c_struct(defn)
    return c_struct_to_yaml_fields(defn), defn.metadata


def build_spec_from_c_struct(raw_input: str, user_input: dict[str, Any] | None) -> ExtensionSpec:
    data = dict(user_input or {})
    spec = build_spec(raw_input, data)

    if data.get("variants"):
        raise ValueError("variants batch must be processed by state_machine, not build_spec_from_c_struct")

    if spec.add is None:
        spec.add = False

    if data.get("empty_payload"):
        source = _empty_struct_source()
        yaml_fields, metadata = _parse_one_struct(source)
    else:
        source, path = load_c_struct_source(data, "c_struct", "c_struct_path")
        yaml_fields, metadata = _parse_one_struct(source, path=path)
    spec.fields = yaml_fields
    _apply_struct_metadata(spec, metadata)

    if spec.pair or data.get("pair"):
        spec.pair = True
        if data.get("resp_empty_payload"):
            spec.resp_fields = []
        else:
            resp_source, resp_path = load_c_struct_source(
                data, "resp_c_struct", "resp_c_struct_path",
            )
            resp_fields, resp_meta = _parse_one_struct(resp_source, path=resp_path)
            spec.resp_fields = resp_fields
            if resp_meta.resp_description and not spec.resp_description:
                spec.resp_description = resp_meta.resp_description
            elif resp_meta.description and not spec.resp_description:
                spec.resp_description = resp_meta.description

    return spec


def _empty_struct_source(*, struct_name: str = "payload_t") -> str:
    return (
        f"typedef struct __attribute__((packed)) {{\n"
        f"}} {struct_name};\n"
    )


def build_spec_from_variant_entry(raw_input: str, entry: dict[str, Any]) -> ExtensionSpec:
    merged = dict(entry)
    return build_spec_from_c_struct(raw_input, merged)
