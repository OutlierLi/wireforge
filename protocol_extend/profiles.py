"""Protocol-specific extension profiles (CSG 2016 / DLT645-2007)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from protocol_extend.dlt645_funcs import DEFAULT_DLT645_FUNC, resolve_dlt645_func
from protocol_extend.fields import missing_field_metadata, field_to_yaml
from protocol_extend.schema import (
    ExtensionSpec,
    afn_di_router_id,
    afn_has_builtin_router,
    normalize_afn,
    normalize_di,
    normalize_dir,
    normalize_func,
    normalize_protocol,
    router_compile_hint,
)

ROOT = Path(__file__).resolve().parent.parent

# Tests may monkeypatch to redirect all extension writes.
EXTENSIONS_DIR_OVERRIDE: Path | None = None


@dataclass(frozen=True)
class ProtocolProfile:
    id: str
    short: str
    label: str

    def extensions_dir(self, root: Path = ROOT) -> Path:
        if EXTENSIONS_DIR_OVERRIDE is not None:
            return EXTENSIONS_DIR_OVERRIDE
        return root / "protocol_tool" / "protocols" / self.id / "variants" / "extensions"

    def variants_scan_dir(self, root: Path = ROOT) -> Path:
        return root / "protocol_tool" / "protocols" / self.id / "variants"

    def compile_name(self) -> str:
        return self.id

    def detect_from_text(self, text: str) -> bool:
        raise NotImplementedError

    def missing_c_struct_input(self, user_input: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def apply_defaults(self, spec: ExtensionSpec) -> None:
        raise NotImplementedError

    def missing_fields(self, spec: ExtensionSpec) -> list[str]:
        raise NotImplementedError

    def extension_filename(self, spec: ExtensionSpec) -> str:
        raise NotImplementedError

    def build_variants(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        raise NotImplementedError

    def render_extension_yaml(self, spec: ExtensionSpec, raw_input: str) -> str:
        variants = self.build_variants(spec)
        doc = {
            "_comment": f"WireForge extension — created {datetime.now().astimezone().isoformat(timespec='seconds')}",
            "_raw_input": raw_input,
            "variants": variants,
        }
        header = self._yaml_header(spec)
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

    def _yaml_header(self, spec: ExtensionSpec) -> str:
        raise NotImplementedError

    def route_params_for(self, spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
        raise NotImplementedError

    def expected_route_param_sets(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        raise NotImplementedError

    def route_handle_args(self, spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
        return self.route_params_for(spec, dir_value=dir_value)

    def match_collides(
        self,
        match: dict[str, Any],
        want_di: str,
        want_dir: int | None,
        want_add: int | None,
        *,
        selector_field: str = "di",
    ) -> bool:
        raise NotImplementedError

    def conflict_keys(self, spec: ExtensionSpec) -> list[tuple[str, int | None, int | None]]:
        raise NotImplementedError

    def has_builtin_router(self, spec: ExtensionSpec) -> bool:
        return True

    def router_hint(self, spec: ExtensionSpec) -> str:
        return ""


def _body_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from protocol_extend.yaml_writer import _body_fields as _impl

    return _impl(fields)


class CsgProfile(ProtocolProfile):
    def __init__(self) -> None:
        super().__init__(id="csg_2016", short="csg", label="CSG 2016")

    def detect_from_text(self, text: str) -> bool:
        if re.search(r"\bafn\b", text, re.I):
            return True
        if re.search(r"\bcsg\b", text, re.I):
            return True
        if re.search(r"\bE8[0-9A-Fa-f]{6}\b", text):
            return True
        if "南网" in text:
            return True
        return False

    def missing_c_struct_input(self, user_input: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        if not user_input.get("afn"):
            missing.append("afn")
        if not user_input.get("di"):
            missing.append("di")
        has_main = bool(user_input.get("c_struct") or user_input.get("c_struct_path"))
        has_empty = bool(user_input.get("empty_payload"))
        if not has_main and not has_empty and not user_input.get("variants"):
            missing.append("c_struct|c_struct_path|empty_payload")
        if user_input.get("pair"):
            has_resp = bool(user_input.get("resp_c_struct") or user_input.get("resp_c_struct_path"))
            has_resp_empty = bool(user_input.get("resp_empty_payload"))
            if not has_resp and not has_resp_empty:
                missing.append("resp_c_struct|resp_c_struct_path|resp_empty_payload")
        return missing

    def apply_defaults(self, spec: ExtensionSpec) -> None:
        if spec.add is None:
            spec.add = False

    def missing_fields(self, spec: ExtensionSpec) -> list[str]:
        missing: list[str] = []
        if not spec.di:
            missing.append("di")
        if spec.afn is None:
            missing.append("afn")
        if not spec.description:
            missing.append("description")
        if spec.afn is not None:
            if spec.add is None:
                missing.append("add")
            if spec.afn != 0 and spec.dir is None and not spec.pair:
                missing.append("dir")
        if spec.fields:
            missing.extend(missing_field_metadata(spec.fields))
        if spec.resp_fields:
            missing.extend(missing_field_metadata(spec.resp_fields, prefix="resp_fields"))
        return missing

    def extension_filename(self, spec: ExtensionSpec) -> str:
        if spec.afn is None:
            raise ValueError("afn is required for extension filename")
        di = spec.di.upper().replace(" ", "")
        if len(di) != 8 or not re.fullmatch(r"[0-9A-F]{8}", di):
            raise ValueError(f"DI must be 8 hex chars (4 bytes), got {spec.di!r}")
        if not di.startswith("E8"):
            raise ValueError(f"CSG DI must start with E8, got {di}")
        return f"{spec.afn:02X}_{di}.yaml"

    def build_variants(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        if spec.afn is None:
            raise ValueError("afn is required")
        variants: list[dict[str, Any]] = []
        if spec.pair:
            req_desc = spec.description or "扩展下行请求"
            resp_desc = spec.resp_description or f"{req_desc}响应"
            if spec.afn == 0:
                variants.append(self._variant_entry(spec, suffix="req", description=req_desc, dir_value=None, fields=spec.fields))
                variants.append(self._variant_entry(spec, suffix="resp", description=resp_desc, dir_value=None, fields=spec.resp_fields or spec.fields))
            else:
                variants.append(self._variant_entry(spec, suffix="down", description=req_desc, dir_value=0, fields=spec.fields))
                variants.append(self._variant_entry(spec, suffix="up", description=resp_desc, dir_value=1, fields=spec.resp_fields or spec.fields))
        else:
            dir_val = spec.dir if spec.afn != 0 else None
            suffix = "down" if dir_val == 0 else "up" if dir_val == 1 else "msg"
            variants.append(self._variant_entry(
                spec, suffix=suffix, description=spec.description, dir_value=dir_val, fields=spec.fields,
            ))
        return variants

    def _variant_entry(
        self,
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
            "body": {"type": "struct", "fields": _body_fields(fields)},
        }

    def _yaml_header(self, spec: ExtensionSpec) -> str:
        return (
            f"# CSG 2016 扩展报文 — {spec.description}\n"
            f"# AFN={spec.afn:02X} DI={spec.di}\n"
            f"# 由 protocol_extend_run 生成\n\n"
        )

    def route_params_for(self, spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "proto": self.short,
            "afn": f"{spec.afn:02X}" if spec.afn is not None else "",
            "di": spec.di.upper(),
        }
        if dir_value is not None:
            params["dir"] = "downlink" if dir_value == 0 else "uplink"
        if spec.add is not None:
            params["has_address"] = spec.add
        return params

    def expected_route_param_sets(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        if spec.pair:
            if spec.afn == 0:
                base = self.route_params_for(spec, dir_value=None)
                return [base, base]
            return [
                self.route_params_for(spec, dir_value=0),
                self.route_params_for(spec, dir_value=1),
            ]
        dir_val = spec.dir if spec.afn not in (None, 0) else None
        return [self.route_params_for(spec, dir_value=dir_val)]

    def match_collides(
        self,
        match: dict[str, Any],
        want_di: str,
        want_dir: int | None,
        want_add: int | None,
        *,
        selector_field: str = "di",
    ) -> bool:
        del selector_field
        di = str(match.get("di", "")).upper().replace(" ", "")
        if di != want_di:
            return False
        entry_add = match.get("control.add")
        if want_add is not None and entry_add is not None and int(entry_add) != want_add:
            return False
        entry_dir = match.get("control.dir")
        if want_dir is not None:
            if entry_dir is None:
                return False
            if int(entry_dir) != want_dir:
                return False
        return True

    def conflict_keys(self, spec: ExtensionSpec) -> list[tuple[str, int | None, int | None]]:
        keys: list[tuple[str, int | None, int | None]] = []
        if spec.pair:
            if spec.afn == 0:
                keys.extend([(spec.di, None, spec.add), (spec.di, None, spec.add)])
            else:
                keys.extend([(spec.di, 0, spec.add), (spec.di, 1, spec.add)])
        else:
            d = spec.dir if spec.afn not in (None, 0) else None
            keys.append((spec.di, d, spec.add))
        return keys

    def has_builtin_router(self, spec: ExtensionSpec) -> bool:
        return spec.afn is not None and afn_has_builtin_router(spec.afn)

    def router_hint(self, spec: ExtensionSpec) -> str:
        if spec.afn is None:
            return ""
        return router_compile_hint(spec.afn)


class Dlt645Profile(ProtocolProfile):
    def __init__(self) -> None:
        super().__init__(id="dlt645_2007", short="dlt645", label="DL/T 645-2007")

    def detect_from_text(self, text: str) -> bool:
        if "645" in text:
            return True
        if re.search(r"\bdlt\s*645\b", text, re.I):
            return True
        if re.search(r"\bfunc\b", text, re.I):
            return True
        if "电表" in text and "读数据" in text:
            return True
        return False

    def missing_c_struct_input(self, user_input: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        if not user_input.get("di"):
            missing.append("di")
        has_main = bool(user_input.get("c_struct") or user_input.get("c_struct_path"))
        has_empty = bool(user_input.get("empty_payload"))
        if not has_main and not has_empty and not user_input.get("variants"):
            missing.append("c_struct|c_struct_path|empty_payload")
        if user_input.get("pair"):
            has_resp = bool(user_input.get("resp_c_struct") or user_input.get("resp_c_struct_path"))
            has_resp_empty = bool(user_input.get("resp_empty_payload"))
            if not has_resp and not has_resp_empty:
                missing.append("resp_c_struct|resp_c_struct_path|resp_empty_payload")
        return missing

    def apply_defaults(self, spec: ExtensionSpec) -> None:
        if spec.func is None:
            spec.func = DEFAULT_DLT645_FUNC
        func_def = resolve_dlt645_func(spec.func)
        if not spec.pair and spec.dir is None:
            spec.dir = func_def.default_dir

    def _func_def(self, spec: ExtensionSpec):
        self.apply_defaults(spec)
        return resolve_dlt645_func(spec.func)

    def missing_fields(self, spec: ExtensionSpec) -> list[str]:
        self.apply_defaults(spec)
        missing: list[str] = []
        if not spec.di:
            missing.append("di")
        if not spec.description:
            missing.append("description")
        if spec.func is None:
            missing.append("func")
        if spec.fields:
            missing.extend(missing_field_metadata(spec.fields))
        if spec.resp_fields:
            missing.extend(missing_field_metadata(spec.resp_fields, prefix="resp_fields"))
        return missing

    def extension_filename(self, spec: ExtensionSpec) -> str:
        self.apply_defaults(spec)
        di = spec.di.upper().replace(" ", "")
        if len(di) != 8 or not re.fullmatch(r"[0-9A-F]{8}", di):
            raise ValueError(f"DI must be 8 hex chars (4 bytes), got {spec.di!r}")
        func = spec.func if spec.func is not None else DEFAULT_DLT645_FUNC
        return f"{func:02X}_{di}.yaml"

    def _router_id(self, spec: ExtensionSpec) -> str:
        return self._func_def(spec).router

    def _match_for(self, spec: ExtensionSpec, func_def) -> dict[str, Any]:
        selector = func_def.selector_field
        key = spec.di.upper().replace(" ", "")
        return {selector: key}

    def build_variants(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        func_def = self._func_def(spec)
        router = func_def.router
        di_clean = spec.di.upper()
        func_hex = f"{func_def.func:02x}"
        match = self._match_for(spec, func_def)

        if spec.pair:
            resp_desc = spec.resp_description or f"{spec.description or func_def.description}响应"
            return [{
                "kind": "variant",
                "id": f"dlt645_2007.ext.{func_hex}_{di_clean.lower()}_resp",
                "description": resp_desc,
                "router": router,
                "match": match,
                "body": {"type": "struct", "fields": _body_fields(spec.resp_fields or spec.fields)},
            }]

        suffix = "resp" if spec.dir == 1 else "req"
        return [{
            "kind": "variant",
            "id": f"dlt645_2007.ext.{func_hex}_{di_clean.lower()}_{suffix}",
            "description": spec.description or func_def.description or "扩展 DI 载荷",
            "router": router,
            "match": match,
            "body": {"type": "struct", "fields": _body_fields(spec.fields)},
        }]

    def _yaml_header(self, spec: ExtensionSpec) -> str:
        func = spec.func if spec.func is not None else DEFAULT_DLT645_FUNC
        return (
            f"# DL/T 645-2007 扩展报文 — {spec.description}\n"
            f"# FUNC=0x{func:02X} DI={spec.di}\n"
            f"# 由 protocol_extend_run 生成\n\n"
        )

    def route_params_for(self, spec: ExtensionSpec, *, dir_value: int | None) -> dict[str, Any]:
        self.apply_defaults(spec)
        func_def = resolve_dlt645_func(spec.func)
        params: dict[str, Any] = {
            "proto": self.short,
            "func": f"{spec.func:02X}" if spec.func is not None else "11",
        }
        selector = func_def.selector_field
        key = spec.di.upper()
        if selector == "di":
            params["di"] = key
        else:
            params[selector] = key
        if dir_value is not None:
            params["dir"] = "downlink" if dir_value == 0 else "uplink"
        elif spec.dir is not None:
            params["dir"] = "downlink" if spec.dir == 0 else "uplink"
        return params

    def expected_route_param_sets(self, spec: ExtensionSpec) -> list[dict[str, Any]]:
        if spec.pair:
            return [self.route_params_for(spec, dir_value=1)]
        return [self.route_params_for(spec, dir_value=spec.dir)]

    def match_collides(
        self,
        match: dict[str, Any],
        want_di: str,
        want_dir: int | None,
        want_add: int | None,
        *,
        selector_field: str = "di",
    ) -> bool:
        del want_add
        key = str(match.get(selector_field, match.get("di", ""))).upper().replace(" ", "")
        if key != want_di:
            return False
        if want_dir is None:
            return True
        entry_dir = match.get("control.dir")
        if entry_dir is None:
            return want_dir == 1
        return int(entry_dir) == want_dir

    def conflict_keys(self, spec: ExtensionSpec) -> list[tuple[str, int | None, int | None]]:
        if spec.pair:
            return [(spec.di, 1, None)]
        return [(spec.di, spec.dir, None)]

    def has_builtin_router(self, spec: ExtensionSpec) -> bool:
        return self._func_def(spec).builtin

    def router_hint(self, spec: ExtensionSpec) -> str:
        func_def = self._func_def(spec)
        return (
            f"FUNC 0x{func_def.func:02X} 尚无内置 router；扩展 YAML 已写入 extensions/。"
            f"请在 protocol.yaml 添加 {func_def.router}（selector: {func_def.selector_field}）"
            f" 并在对应 message 使用 routed_payload 后运行 bootstrap。"
        )


CSG_PROFILE = CsgProfile()
DLT645_PROFILE = Dlt645Profile()
_PROFILES: dict[str, ProtocolProfile] = {
    "csg_2016": CSG_PROFILE,
    "dlt645_2007": DLT645_PROFILE,
}


def get_profile(protocol: str) -> ProtocolProfile:
    key = normalize_protocol(protocol)
    profile = _PROFILES.get(key)
    if profile is None:
        raise ValueError(f"unsupported protocol for extension: {protocol}")
    return profile


def detect_protocol(raw_input: str, user_input: dict[str, Any] | None = None) -> str:
    data = dict(user_input or {})
    if data.get("protocol"):
        return normalize_protocol(data["protocol"])

    text = raw_input or ""
    lower = text.lower()

    csg_score = sum(1 for p in (CSG_PROFILE,) if p.detect_from_text(lower))
    dlt_score = sum(1 for p in (DLT645_PROFILE,) if p.detect_from_text(lower))
    if "func" in data:
        dlt_score += 2
    if "afn" in data:
        csg_score += 2
    di = normalize_di(data.get("di") or "")
    if di.startswith("E8"):
        csg_score += 2
    elif di and not di.startswith("E8"):
        dlt_score += 2

    if dlt_score > csg_score:
        return "dlt645_2007"
    return "csg_2016"


def input_schema_for(protocol: str) -> list[dict[str, Any]]:
    common = [
        {"name": "protocol", "type": "string", "required": False, "desc": "csg / dlt645（可自动识别）"},
        {"name": "di", "type": "string", "required": True, "desc": "8 位 DI（CSG 如 E8030306；645 如 00010000）"},
        {"name": "c_struct", "type": "string", "required": False, "desc": "inline C 结构体源码（DI payload）"},
        {"name": "c_struct_path", "type": "string", "required": False, "desc": ".h 文件路径"},
        {"name": "dir", "type": "string", "required": False, "desc": "downlink/uplink；645 默认 uplink（读数据应答载荷）"},
        {"name": "description", "type": "string", "required": False, "desc": "报文描述（也可写在 @wireforge 注释）"},
        {"name": "pair", "type": "boolean", "required": False, "desc": "是否生成请求/响应成对 variant"},
        {"name": "empty_payload", "type": "boolean", "required": False, "desc": "true 表示空 payload"},
        {"name": "resp_empty_payload", "type": "boolean", "required": False, "desc": "成对报文响应侧空 payload"},
        {"name": "resp_c_struct", "type": "string", "required": False, "desc": "响应 payload C 结构体源码"},
        {"name": "resp_c_struct_path", "type": "string", "required": False, "desc": "响应 payload .h 路径"},
        {"name": "resp_description", "type": "string", "required": False, "desc": "响应报文描述"},
        {"name": "variants", "type": "array", "required": False, "desc": "批量扩展 manifest"},
    ]
    profile = get_profile(protocol)
    if profile.id == "dlt645_2007":
        return [
            {"name": "func", "type": "string", "required": False,
             "desc": "控制码 FUNC（0x11 读数据/0x14 写数据/0x16 冻结/0x1B 事件清零等；默认 0x11）",
             "default": "0x11"},
            *common,
        ]
    return [
        {"name": "afn", "type": "string", "required": True, "desc": "应用功能码 AFN（hex 或十进制）"},
        {"name": "add", "type": "boolean", "required": False, "desc": "是否带地址域；默认 false"},
        *common,
    ]
