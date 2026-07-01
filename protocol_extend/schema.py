"""Extension schema — protocol-aware via profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROOT_PROTOCOL = "csg_2016"
SUPPORTED_PROTOCOLS = {"csg_2016", "csg", "dlt645_2007", "dlt645"}

from protocol_extend.schema_csg import (  # noqa: E402
    AFN00_NO_DIR,
    AFN_ROUTERS,
    afn_di_router_id,
    afn_has_builtin_router,
    router_compile_hint,
)


@dataclass
class ExtensionSpec:
    protocol: str = "csg_2016"
    afn: int | None = None
    func: int | None = None
    di: str = ""
    description: str = ""
    dir: int | None = None
    add: bool | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    pair: bool = False
    resp_description: str = ""
    resp_fields: list[dict[str, Any]] = field(default_factory=list)

    @property
    def profile(self):
        from protocol_extend.profiles import get_profile
        return get_profile(self.protocol)

    def to_partial(self) -> dict[str, Any]:
        out: dict[str, Any] = {"protocol": self.profile.short}
        if self.afn is not None:
            out["afn"] = f"{self.afn:02X}"
        if self.func is not None:
            out["func"] = f"0x{self.func:02X}"
        if self.di:
            out["di"] = self.di
        if self.description:
            out["description"] = self.description
        if self.dir is not None:
            out["dir"] = "downlink" if self.dir == 0 else "uplink"
        if self.add is not None:
            out["add"] = self.add
        if self.fields:
            out["fields"] = self.fields
        if self.pair:
            out["pair"] = True
        return out

    def router_id(self) -> str:
        if self.protocol == "dlt645_2007":
            return self.profile._router_id(self)  # type: ignore[attr-defined]
        if self.afn is None:
            raise ValueError("afn is required")
        return afn_di_router_id(self.afn)

    def afn_uses_dir(self) -> bool:
        return self.afn is not None and self.afn != AFN00_NO_DIR


def normalize_protocol(raw: Any) -> str:
    text = str(raw or "csg").strip().lower()
    if text in {"csg", "csg_2016", "csg2016"}:
        return "csg_2016"
    if text in {"dlt645", "645", "dl/t645", "dlt645_2007"}:
        return "dlt645_2007"
    return text


def normalize_afn(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    if text.isdigit():
        return int(text, 10)
    try:
        return int(text, 16)
    except ValueError:
        return None


def normalize_func(raw: Any) -> int | None:
    return normalize_afn(raw)


def normalize_di(raw: Any) -> str:
    if not raw:
        return ""
    clean = str(raw).strip().replace(" ", "").replace("-", "").upper()
    if len(clean) == 8 and all(c in "0123456789ABCDEF" for c in clean):
        return clean
    return ""


def normalize_dir(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        return 0 if raw == 0 else 1
    text = str(raw).strip().lower()
    if text in {"0", "downlink", "down", "下行", "请求"}:
        return 0
    if text in {"1", "uplink", "up", "上行", "响应"}:
        return 1
    return None


def normalize_add(raw: Any) -> bool | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "带地址", "有地址"}:
        return True
    if text in {"0", "false", "no", "n", "off", "无地址", "不带地址"}:
        return False
    return None


def missing_schema_input(user_input: dict[str, Any] | None) -> list[str]:
    from protocol_extend.profiles import detect_protocol, get_profile
    data = dict(user_input or {})
    protocol = detect_protocol("", data)
    return get_profile(protocol).missing_schema_input(data)


def missing_fields(spec: ExtensionSpec) -> list[str]:
    from doc_parser.metadata_extractor import derive_afn_from_di, infer_afn_from_semantics

    if spec.protocol == "csg_2016":
        if not spec.di:
            pass
        elif spec.afn is None and spec.di:
            derived = derive_afn_from_di(spec.di)
            if derived is None:
                derived = infer_afn_from_semantics(spec.description or "")
            if derived is not None:
                spec.afn = derived
    spec.profile.apply_defaults(spec)
    return spec.profile.missing_fields(spec)


def match_key(spec: ExtensionSpec, *, dir_value: int | None = None) -> tuple[str, int | None, int | None]:
    d = dir_value if dir_value is not None else spec.dir
    return (spec.di, d, spec.add)


def partial_with_defaults(spec: ExtensionSpec) -> dict[str, Any]:
    from protocol_extend.profiles import input_schema_for
    partial = spec.to_partial()
    for item in input_schema_for(spec.protocol):
        name = item["name"]
        if "default" not in item:
            continue
        if name not in partial:
            partial[name] = item["default"]
    return partial


INPUT_SCHEMA: list[dict[str, Any]] = [
    {"name": "afn", "type": "string", "required": True, "desc": "CSG AFN, hex or decimal"},
    {"name": "di", "type": "string", "required": True, "desc": "8-hex DI, for example E8030304"},
    {"name": "fields", "type": "array", "required": False, "desc": "Agent-authored payload schema fields"},
    {"name": "dir", "type": "string", "required": False, "desc": "downlink/uplink; optional for pair=true"},
    {"name": "description", "type": "string", "required": False, "desc": "message description"},
    {"name": "add", "type": "boolean", "required": False, "desc": "whether CSG address area is present; default false"},
    {"name": "pair", "type": "boolean", "required": False, "desc": "generate request/response variants"},
    {"name": "empty_payload", "type": "boolean", "required": False, "desc": "true means payload has no fields"},
    {"name": "resp_empty_payload", "type": "boolean", "required": False, "desc": "pair response has no fields"},
    {"name": "resp_fields", "type": "array", "required": False, "desc": "Agent-authored response payload schema fields"},
    {"name": "resp_description", "type": "string", "required": False, "desc": "response message description"},
    {"name": "variants", "type": "array", "required": False, "desc": "batch extension entries; each item contains afn/di/fields"},
]
