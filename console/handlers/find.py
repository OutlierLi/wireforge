"""/find 命令处理器 — 搜索协议消息定义。

数据源: compiled/protocol_map.yaml（预编译索引，含所有 entry 的 name、description、route_params、fields）

用法:
  /find 初始化档案           → 关键字搜索（匹配 name + description + DI）
  /find E8020102             → DI 精确匹配（也支持关键字回退）
  /find --proto=csg --afn=0x01 初始化 → 组合过滤
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from console.response import ok, fail

ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "compiled" / "protocol_map.yaml"

# 协议名标准化：用户简称 → protocol_map.yaml 中的 proto 值
_NORMALIZE_PROTO = {
    "dlt645": "dlt645",
    "dlt645_2007": "dlt645",
    "csg": "csg",
    "csg_2016": "csg",
}


def _normalize_hex(value: str) -> str:
    """归一化 hex 值：去掉 0x 前缀、去空格、大写。"""
    v = value.strip().replace(" ", "")
    if v.lower().startswith("0x"):
        v = v[2:]
    return v.upper()


def _load_map() -> dict[str, Any]:
    """加载 protocol_map.yaml。文件不存在时返回空结构。"""
    if not MAP_PATH.exists():
        return {"protocols": {}}
    with open(MAP_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _entry_haystack(entry: dict) -> str:
    """构建 entry 的全文搜索 haystack（大小写不敏感）。"""
    rp = entry.get("route_params", {}) or {}
    parts = [
        entry.get("name", ""),
        entry.get("description", ""),
        rp.get("proto", ""),
        rp.get("di", ""),
        rp.get("afn", ""),
        rp.get("func", ""),
        rp.get("dir", ""),
    ]
    # 字段名也加入搜索
    for f in entry.get("fields") or []:
        parts.append(str(f))
    # path 中的 key=value 对
    for p in entry.get("path") or []:
        parts.append(str(p))
    return " ".join(parts).lower()


def _match_entry(entry: dict, args: dict) -> bool:
    """检查单条 entry 是否匹配搜索条件。"""
    rp = entry.get("route_params", {}) or {}

    # --proto 精确匹配
    if args.get("proto"):
        want = _NORMALIZE_PROTO.get(args["proto"], args["proto"])
        if rp.get("proto") != want:
            return False

    # --di 精确匹配（忽略大小写和空格）
    if args.get("di"):
        want_di = args["di"].replace(" ", "").upper()
        entry_di = (rp.get("di") or "").upper()
        if entry_di != want_di:
            return False

    # --afn 精确匹配（hex 归一化）
    if args.get("afn"):
        want_afn = _normalize_hex(args["afn"])
        entry_afn = _normalize_hex(rp.get("afn") or "")
        if entry_afn != want_afn:
            return False

    # --func 精确匹配（hex 归一化）
    if args.get("func"):
        want_func = _normalize_hex(args["func"])
        entry_func = _normalize_hex(rp.get("func") or "")
        if entry_func != want_func:
            return False

    # --dir 精确匹配
    if args.get("dir"):
        if rp.get("dir", "").lower() != args["dir"].lower():
            return False

    # --meaning / -q 关键字搜索（同旧项目 meaning，全文模糊匹配）
    q = args.get("q", "")
    if q:
        haystack = _entry_haystack(entry)
        q_lower = q.lower().replace(" ", "")
        # 直接子串匹配
        if q_lower not in haystack and q_lower not in haystack.replace(",", " "):
            # 带空格的原始搜索词（如"初始化档案"）
            if q.strip().lower() not in haystack.replace(",", " "):
                return False

    # --filter 额外 AND 过滤条件（支持多个，全部需匹配）
    filter_terms = args.get("filter_terms", [])
    if filter_terms:
        haystack = _entry_haystack(entry)
        for term in filter_terms:
            t = str(term).lower().replace(" ", "")
            if t not in haystack and t not in haystack.replace(",", " "):
                if str(term).strip().lower() not in haystack.replace(",", " "):
                    return False

    return True


def _format_entry(entry: dict) -> dict:
    """格式化单条 entry 为统一输出结构。"""
    rp = entry.get("route_params", {}) or {}
    return {
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "leaf_id": entry.get("leaf_id", ""),
        "route_params": {
            "proto": rp.get("proto", ""),
            "afn": rp.get("afn", ""),
            "di": rp.get("di", ""),
            "func": rp.get("func", ""),
            "dir": rp.get("dir", ""),
        },
        "fields": entry.get("fields") or [],
        "path": entry.get("path") or [],
    }


def handle(args: dict[str, Any]) -> dict:
    """执行 /find 命令。

    args 可包含: proto, q, di, afn, func, dir
    位置参数会自动放入 args["_"] 作为 keyword。
    """
    # --meaning 是关键字搜索参数
    if not args.get("q"):
        args = {**args, "q": args.get("meaning", "")}

    # --filter 聚合成 filter_terms（支持多个 --filter=xxx）
    filter_raw = args.get("filter", [])
    if isinstance(filter_raw, str):
        filter_raw = [filter_raw]
    if isinstance(filter_raw, list) and filter_raw:
        existing = args.get("filter_terms", [])
        if isinstance(existing, str):
            existing = [existing]
        args["filter_terms"] = list(existing) + list(filter_raw)

    data = _load_map()
    protocols = data.get("protocols", {})

    if not protocols:
        return fail("protocol_map.yaml not found, run compile first")

    results: list[dict] = []
    searched_protocols: set[str] = set()

    # 统一遍历所有协议条目，_match_entry 负责 proto 过滤
    for proto_id, protocol_data in protocols.items():
        for entry in protocol_data.get("entries", []):
            if _match_entry(entry, args):
                searched_protocols.add(proto_id)
                results.append(_format_entry(entry))

    return ok({
        "count": len(results),
        "protocols": sorted(searched_protocols),
        "results": results,
        "query": {
            "proto": args.get("proto"),
            "meaning": args.get("q") or args.get("meaning"),
            "filter": args.get("filter_terms"),
            "di": args.get("di"),
            "afn": args.get("afn"),
            "func": args.get("func"),
            "dir": args.get("dir"),
        },
    })
