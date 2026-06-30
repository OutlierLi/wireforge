"""CSG domain extended types — prefer named types over bare codec primitives."""

from __future__ import annotations

import re
from typing import Any

from protocol_extend.candidate import FieldCandidate

# Names registered in protocol_tool/protocols/csg_2016/types/shared.yaml
NODE_ADDRESS = "node_address"

DOMAIN_TYPE_NAMES = frozenset({NODE_ADDRESS})

_ADDRESS_KEYWORDS = (
    "节点地址",
    "从节点地址",
    "主节点地址",
    "父节点地址",
    "目的地址",
    "源地址",
    "通信地址",
    "表地址",
    "从节点通信地址",
)

_ADDRESS_LIST_KEYWORDS = (
    "地址列表",
    "节点列表",
    "节点地址列表",
    "从节点地址列表",
)

_ADDRESS_NAME_RE = re.compile(
    r"(?:^|_)(?:node|slave|blacklist|master|parent|dest|src|source|addr)(?:s|es|_)?$|地址",
    re.I,
)


def is_domain_type(type_name: str) -> bool:
    return type_name in DOMAIN_TYPE_NAMES


def _text_blob(candidate: FieldCandidate) -> str:
    parts = [candidate.name, candidate.desc or ""]
    parts.extend(candidate.evidence)
    return " ".join(p for p in parts if p)


def is_node_address(candidate: FieldCandidate) -> bool:
    blob = _text_blob(candidate)
    if not blob:
        return False
    if any(kw in blob for kw in _ADDRESS_KEYWORDS):
        return True
    if _ADDRESS_NAME_RE.search(candidate.name):
        return True
    if candidate.bytes == 6 and "地址" in blob:
        return True
    return False


def is_node_address_list(candidate: FieldCandidate) -> bool:
    blob = _text_blob(candidate)
    if candidate.agent_type == "array":
        if any(kw in blob for kw in _ADDRESS_LIST_KEYWORDS):
            return True
        if _ADDRESS_NAME_RE.search(candidate.name) and ("list" in candidate.name.lower() or "列表" in blob):
            return True
    return any(kw in blob for kw in _ADDRESS_LIST_KEYWORDS) and candidate.agent_type == "array"


def match_domain_type(candidate: FieldCandidate) -> str | None:
    """Return preferred extended type name, or None."""
    if candidate.semantic_override:
        override = str(candidate.semantic_override).strip().lower()
        if override in DOMAIN_TYPE_NAMES:
            return override
        if override in ("address", "node_addr", "node_address"):
            return NODE_ADDRESS

    if candidate.agent_type == "array":
        return None

    if is_node_address(candidate):
        return NODE_ADDRESS
    return None


def match_array_item_domain_type(candidate: FieldCandidate) -> str | None:
    if candidate.item_type and is_domain_type(str(candidate.item_type)):
        return str(candidate.item_type)
    if is_node_address_list(candidate) or is_node_address(candidate):
        return NODE_ADDRESS
    if candidate.item_type in (None, "", "bytes", "bcd", "hex") and candidate.bytes == 6:
        if is_node_address(candidate):
            return NODE_ADDRESS
    item_fields = candidate.item_fields or []
    if len(item_fields) == 1 and isinstance(item_fields[0], dict):
        child = candidate_from_dict_item(item_fields[0])
        if is_node_address(child):
            return NODE_ADDRESS
    return None


def candidate_from_dict_item(field: dict[str, Any]) -> FieldCandidate:
    from protocol_extend.candidate import candidate_from_agent_field
    return candidate_from_agent_field(field)


def domain_type_entry(type_name: str) -> dict[str, Any]:
    return {"type": type_name}
