"""/route 命令处理器 — 解析路由路径，返回构造帧所需的字段 schema。

用法:
  /route --proto=csg --afn=0x06 --di=E8010601 --dir=uplink
  /route --proto=dlt645 --func=0x11 --di=00010000 --dir=downlink

Agent 工作流:
  1. /route → 获取 path + input_schema
  2. 根据 input_schema 填充字段值
  3. /build → 构造帧
"""

from __future__ import annotations

from typing import Any

from console.response import ok, fail


def handle(args: dict[str, Any]) -> dict:
    from console.build_resolver import resolve

    proto = args.get("proto", "")
    func = args.get("func", "")
    afn = args.get("afn", "")
    di = args.get("di", "")
    dir_val = args.get("dir", args.get("direction", ""))

    if not proto:
        return fail("缺少 --proto。用法: /route --proto=csg --afn=0x06 --di=E8010601 --dir=uplink")

    target_info: dict[str, Any] = {"proto": proto}
    if func:
        target_info["func"] = func
    if afn:
        target_info["afn"] = afn
    if di:
        target_info["di"] = di
    if dir_val:
        target_info["dir"] = dir_val
    if args.get("has_address") is not None:
        target_info["has_address"] = args["has_address"]

    try:
        target = resolve(target_info)
    except Exception as e:
        return fail(str(e))

    # 分类字段：定位参数、派生字段、用户输入
    target_keys = {"func", "afn", "di", "dir", "direction"}
    locator = {k: v for k, v in target.target_info.items()
               if k in target_keys}

    return ok({
        "protocol": target.protocol,
        "path": target.path,
        "message_id": target.message_id,
        "variant_id": target.variant_id,
        "locator": locator,
        "input_schema": [f.to_dict() for f in target.input_schema],
        "derived_fields": {k: v for k, v in target.derived_fields.items()
                          if k != "seq"},
        "frame_defaults": target.frame_defaults,
    })
