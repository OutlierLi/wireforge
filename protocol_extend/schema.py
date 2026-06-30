"""CSG 2016 extension schema — AFN routers, required params, input_schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ROOT_PROTOCOL = "csg_2016"
SUPPORTED_PROTOCOLS = {ROOT_PROTOCOL, "csg"}

# AFN 00–07 per protocol.yaml
AFN_ROUTERS: dict[int, str] = {
    0x00: "afn00_di_router",
    0x01: "afn01_di_router",
    0x02: "afn02_di_router",
    0x03: "afn03_di_router",
    0x04: "afn04_di_router",
    0x05: "afn05_di_router",
    0x06: "afn06_di_router",
    0x07: "afn07_di_router",
}

AFN00_NO_DIR = 0x00

def afn_di_router_id(afn: int) -> str:
    """Return DI router for AFN — built-in 00–07 or convention ``afnXX_di_router``."""
    return AFN_ROUTERS.get(afn) or f"afn{afn:02x}_di_router"


def afn_has_builtin_router(afn: int | None) -> bool:
    return afn is not None and afn in AFN_ROUTERS


def router_compile_hint(afn: int) -> str:
    router = afn_di_router_id(afn)
    return (
        f"AFN {afn:02X} 尚无内置 router；扩展 YAML 已写入 extensions/。"
        f"请在 protocol.yaml 添加 {router}（及 afn_router 分组）后运行 bootstrap。"
    )

INPUT_SCHEMA: list[dict[str, Any]] = [
    {"name": "afn", "type": "string", "required": True, "desc": "应用功能码 AFN（hex 或十进制）"},
    {"name": "di", "type": "string", "required": True, "desc": "8 位 CSG 数据标识 DI（如 E8030304）"},
    {"name": "c_struct", "type": "string", "required": False, "desc": "inline C 结构体源码（DI payload）"},
    {"name": "c_struct_path", "type": "string", "required": False, "desc": ".h 文件路径（与 c_struct 二选一）"},
    {"name": "dir", "type": "string", "required": False, "desc": "downlink/uplink；成对报文 pair=true 时可省略"},
    {"name": "description", "type": "string", "required": False, "desc": "报文描述（也可写在 @wireforge 注释）"},
    {"name": "add", "type": "boolean", "required": False, "desc": "是否带地址域；默认 false"},
    {"name": "pair", "type": "boolean", "required": False, "desc": "是否生成请求/响应成对 variant"},
    {"name": "empty_payload", "type": "boolean", "required": False, "desc": "true 表示 DI payload 无字段（空 struct）"},
    {"name": "resp_empty_payload", "type": "boolean", "required": False, "desc": "成对报文响应侧空 payload"},
    {"name": "resp_c_struct", "type": "string", "required": False, "desc": "响应 payload C 结构体源码"},
    {"name": "resp_c_struct_path", "type": "string", "required": False, "desc": "响应 payload .h 路径"},
    {"name": "resp_description", "type": "string", "required": False, "desc": "响应报文描述"},
    {"name": "variants", "type": "array", "required": False, "desc": "批量扩展 manifest（每项含 afn/di/c_struct*）"},
]


@dataclass
class ExtensionSpec:
    protocol: str = "csg_2016"
    afn: int | None = None
    di: str = ""
    description: str = ""
    dir: int | None = None
    add: bool | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    pair: bool = False
    resp_description: str = ""
    resp_fields: list[dict[str, Any]] = field(default_factory=list)

    def to_partial(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.protocol:
            out["protocol"] = self.protocol
        if self.afn is not None:
            out["afn"] = f"{self.afn:02X}"
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
        if self.afn is None:
            raise ValueError("afn is required")
        return afn_di_router_id(self.afn)

    def afn_uses_dir(self) -> bool:
        return self.afn is not None and self.afn != AFN00_NO_DIR


def normalize_protocol(raw: Any) -> str:
    text = str(raw or "csg").strip().lower()
    if text in {"csg", "csg_2016", "csg2016"}:
        return ROOT_PROTOCOL
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


from protocol_extend.fields import FIELD_DSL_EXAMPLES, missing_field_metadata


def missing_c_struct_input(user_input: dict[str, Any] | None) -> list[str]:
    """Return missing keys for C struct extension input."""
    data = dict(user_input or {})
    missing: list[str] = []
    if not data.get("afn"):
        missing.append("afn")
    if not data.get("di"):
        missing.append("di")
    has_main = bool(data.get("c_struct") or data.get("c_struct_path"))
    has_empty = bool(data.get("empty_payload"))
    if not has_main and not has_empty and not data.get("variants"):
        missing.append("c_struct|c_struct_path|empty_payload")
    if data.get("pair"):
        has_resp = bool(data.get("resp_c_struct") or data.get("resp_c_struct_path"))
        has_resp_empty = bool(data.get("resp_empty_payload"))
        if not has_resp and not has_resp_empty:
            missing.append("resp_c_struct|resp_c_struct_path|resp_empty_payload")
    return missing
from doc_parser.metadata_extractor import derive_afn_from_di, infer_afn_from_semantics
def missing_fields(spec: ExtensionSpec) -> list[str]:
    missing: list[str] = []
    if not spec.di:
        missing.append("di")
    if spec.afn is None and spec.di:
        derived = derive_afn_from_di(spec.di)
        if derived is None:
            derived = infer_afn_from_semantics(spec.description or "")
        if derived is not None:
            spec.afn = derived
    if spec.afn is None:
        missing.append("afn")
    if not spec.description:
        missing.append("description")
    if spec.afn is not None:
        if spec.add is None:
            missing.append("add")
        if spec.afn_uses_dir() and spec.dir is None and not spec.pair:
            missing.append("dir")
    if spec.fields:
        missing.extend(missing_field_metadata(spec.fields))
    if spec.resp_fields:
        missing.extend(missing_field_metadata(spec.resp_fields, prefix="resp_fields"))
    return missing


def partial_with_defaults(spec: ExtensionSpec) -> dict[str, Any]:
    partial = spec.to_partial()
    for item in INPUT_SCHEMA:
        name = item["name"]
        if "default" not in item:
            continue
        if name == "protocol":
            partial["protocol"] = item["default"]
        elif name not in partial:
            partial[name] = item["default"]
    return partial


def match_key(spec: ExtensionSpec, *, dir_value: int | None = None) -> tuple[str, int | None, int | None]:
    """Return (di, dir, add) for conflict detection."""
    d = dir_value if dir_value is not None else spec.dir
    return (spec.di, d, spec.add)
