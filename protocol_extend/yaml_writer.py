"""Generate extension variant YAML and write to variants/extensions/."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from protocol_extend.schema import ExtensionSpec

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXTENSIONS_DIR = ROOT / "protocol_tool" / "protocols" / "csg_2016" / "variants" / "extensions"

# Tests may monkeypatch this module attribute.
EXTENSIONS_DIR = DEFAULT_EXTENSIONS_DIR


def _slug(text: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    if ascii_part:
        return ascii_part[:40]
    return "ext"


from protocol_extend.fields import field_to_yaml as _field_to_yaml
def _body_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not fields:
        return []
    return [_field_to_yaml(f) for f in fields]


def _variant_entry(
    spec: ExtensionSpec,
    *,
    suffix: str,
    description: str,
    dir_value: int | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    di_clean = spec.di.upper()
    afn_hex = f"{spec.afn:02x}" if spec.afn is not None else "00"
    variant_id = f"csg_2016.ext.afn{afn_hex}_{di_clean.lower()}_{suffix}"

    match: dict[str, Any] = {"di": di_clean}
    if spec.afn != 0 and dir_value is not None:
        match["control.dir"] = dir_value
    if spec.add is not None:
        match["control.add"] = 1 if spec.add else 0

    return {
        "kind": "variant",
        "id": variant_id,
        "description": description,
        "router": spec.router_id(),
        "match": match,
        "body": {
            "type": "struct",
            "fields": _body_fields(fields),
        },
    }


def build_variants(spec: ExtensionSpec) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    if spec.pair:
        req_desc = spec.description or "扩展下行请求"
        resp_desc = spec.resp_description or f"{req_desc}响应"
        if spec.afn == 0:
            variants.append(_variant_entry(spec, suffix="req", description=req_desc, dir_value=None, fields=spec.fields))
            variants.append(_variant_entry(spec, suffix="resp", description=resp_desc, dir_value=None, fields=spec.resp_fields or spec.fields))
        else:
            variants.append(_variant_entry(spec, suffix="down", description=req_desc, dir_value=0, fields=spec.fields))
            variants.append(_variant_entry(spec, suffix="up", description=resp_desc, dir_value=1, fields=spec.resp_fields or spec.fields))
    else:
        dir_val = spec.dir if spec.afn_uses_dir() else None
        suffix = "down" if dir_val == 0 else "up" if dir_val == 1 else "msg"
        variants.append(_variant_entry(
            spec,
            suffix=suffix,
            description=spec.description,
            dir_value=dir_val,
            fields=spec.fields,
        ))
    return variants


def extension_filename(spec: ExtensionSpec) -> str:
    afn_part = f"{spec.afn:02d}" if spec.afn is not None else "xx"
    di_part = spec.di.upper()
    slug = _slug(spec.description or "extension")
    return f"{afn_part}_{di_part}_{slug}.yaml"


def render_extension_yaml(spec: ExtensionSpec, raw_input: str) -> str:
    variants = build_variants(spec)
    doc = {
        "_comment": f"WireForge extension — created {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "_raw_input": raw_input,
        "variants": variants,
    }
    header = (
        f"# CSG 2016 扩展报文 — {spec.description}\n"
        f"# AFN={spec.afn:02X} DI={spec.di}\n"
        f"# 由 protocol_extend_run 生成，不修改 afn_payloads.yaml\n\n"
    )
    body = yaml.dump(
        {k: v for k, v in doc.items() if not str(k).startswith("_")},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    meta = yaml.dump(
        {"_comment": doc["_comment"], "_raw_input": doc["_raw_input"]},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return header + meta + body


def write_extension_file(spec: ExtensionSpec, raw_input: str, extensions_dir: Path | None = None) -> Path:
    target_dir = extensions_dir or EXTENSIONS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = extension_filename(spec)
    path = target_dir / filename
    if path.exists():
        raise FileExistsError(f"extension file already exists: {path}")
    path.write_text(render_extension_yaml(spec, raw_input), encoding="utf-8")
    return path
