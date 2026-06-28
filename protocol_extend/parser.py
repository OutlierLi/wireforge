"""Heuristic parsing of natural-language extension requests."""

from __future__ import annotations

import re
from typing import Any

from protocol_extend.schema import (
    ExtensionSpec,
    normalize_add,
    normalize_afn,
    normalize_di,
    normalize_dir,
    normalize_protocol,
)


def parse_raw_input(text: str) -> ExtensionSpec:
    spec = ExtensionSpec()
    if not text.strip():
        return spec

    afn_match = re.search(r"AFN\s*0*([0-9A-Fa-f]{1,2})\b", text, re.I)
    if not afn_match:
        afn_match = re.search(r"afn\s*[=:\s]+0x?([0-9A-Fa-f]{1,2})\b", text, re.I)
    if afn_match:
        spec.afn = normalize_afn(afn_match.group(1))

    di_match = re.search(r"DI\s*[=:\s]*([0-9A-Fa-f]{8})\b", text, re.I)
    if not di_match:
        di_match = re.search(r"\b([Ee][0-9A-Fa-f]{7})\b", text)
    if di_match:
        spec.di = normalize_di(di_match.group(1))

    quoted = re.findall(r"[「\"']([^「\"']+)[」\"']", text)
    if quoted:
        spec.description = quoted[0].strip()
    else:
        desc_match = re.search(r"(?:描述|说明)[:：]\s*(.+?)(?:[，,。]|$)", text)
        if desc_match:
            spec.description = desc_match.group(1).strip()
        elif "查询" in text or "扩展" in text:
            chunk = re.sub(r"AFN\s*0*\d+", "", text, flags=re.I)
            chunk = re.sub(r"DI\s*[=:\s]*[0-9A-Fa-f]{8}", "", chunk, flags=re.I)
            chunk = re.sub(r"扩展|CSG|报文|csg|帮我|请", "", chunk, flags=re.I).strip(" ，,。:")
            if chunk and len(chunk) >= 4 and not re.fullmatch(r"一?个?新?报文?", chunk):
                spec.description = chunk

    if re.search(r"下行|请求", text):
        spec.dir = 0
    elif re.search(r"上行|响应", text):
        spec.dir = 1

    if re.search(r"带地址|有地址", text):
        spec.add = True
    elif re.search(r"无地址|不带地址", text):
        spec.add = False

    if re.search(r"成对|请求.*响应|request.*response", text, re.I):
        spec.pair = True

    return spec


def merge_user_input(spec: ExtensionSpec, user_input: dict[str, Any]) -> ExtensionSpec:
    data = dict(user_input or {})
    if "protocol" in data:
        spec.protocol = normalize_protocol(data["protocol"])
    if "afn" in data:
        spec.afn = normalize_afn(data["afn"])
    if "di" in data:
        spec.di = normalize_di(data["di"])
    if "description" in data:
        spec.description = str(data["description"]).strip()
    if "dir" in data:
        spec.dir = normalize_dir(data["dir"])
    if "add" in data:
        spec.add = normalize_add(data["add"])
    if "fields" in data and isinstance(data["fields"], list):
        spec.fields = list(data["fields"])
    if "pair" in data:
        spec.pair = bool(data["pair"])
    if "resp_description" in data:
        spec.resp_description = str(data["resp_description"]).strip()
    if "resp_fields" in data and isinstance(data["resp_fields"], list):
        spec.resp_fields = list(data["resp_fields"])
    return spec


def build_spec(raw_input: str, user_input: dict[str, Any] | None) -> ExtensionSpec:
    spec = parse_raw_input(raw_input or "")
    if user_input:
        spec = merge_user_input(spec, user_input)
    if not spec.protocol or spec.protocol == "csg_2016":
        spec.protocol = normalize_protocol(user_input.get("protocol") if user_input else "csg")
    return spec
