"""/var 命令处理器 — 变量系统入口。

用法:
  /var set <name> --value=<value> [--type=<type>]
  /var get <name>
  /var show [--json]
  /var delete <name>
  /var clear
  /var export --file=<path.yaml>
  /var import --file=<path.yaml> [--mode=merge|replace]
"""

from __future__ import annotations

from typing import Any

from console.response import ok, fail
from console.variable_store import store, VariableError


def handle(args: dict[str, Any]) -> dict:
    sub = args.get("sub", "").strip().lower()
    # 也支持位置参数: /var set <name> --value=...
    positional: list[str] = [str(x) for x in args.get("_", [])]
    if not sub and positional:
        sub = positional[0].strip().lower()
        positional = positional[1:]  # 移除子命令，剩余为位置参数
    # 将调整后的位置参数写回 args，子处理器统一从 positional[0] 取 name
    args = {**args, "_": positional}
    if not sub:
        return fail(
            "缺少子命令。可用: set, get, show, delete, clear, export, import",
            detail={"hint": "用法: /var set <name> --value=<value> [--type=<type>]"},
        )

    handler_map = {
        "set": _handle_set,
        "get": _handle_get,
        "show": _handle_show,
        "delete": _handle_delete,
        "clear": _handle_clear,
        "export": _handle_export,
        "import": _handle_import,
    }

    fn = handler_map.get(sub)
    if not fn:
        return fail(
            f"未知子命令: {sub}。可用: set, get, show, delete, clear, export, import"
        )
    try:
        return fn(args)
    except VariableError as e:
        return fail(str(e), detail={"code": e.code})


# ── 子命令处理 ──────────────────────────────────────────────────────────

def _handle_set(args: dict[str, Any]) -> dict:
    # 变量名来自第一个位置参数
    positional = args.get("_", [])
    name = args.get("name", "")
    if not name and positional:
        name = str(positional[0])
    if not name:
        return fail("缺少变量名。用法: /var set <name> --value=<value> [--type=<type>]")

    value = args.get("value")
    if value is None:
        return fail("缺少 --value。用法: /var set <name> --value=<value> [--type=<type>]")

    vtype = args.get("type", "string")
    entry = store.set(name, value, vtype, source={
        "kind": "user",
        "command": f"/var set {name} --value={value} --type={vtype}",
    })

    return ok({
        "variable": entry,
        "message": f"变量 '{name}' ({vtype}) 已设置。",
    })


def _handle_get(args: dict[str, Any]) -> dict:
    positional = args.get("_", [])
    name = args.get("name", "")
    if not name and positional:
        name = str(positional[0])
    if not name:
        return fail("缺少变量名。用法: /var get <name>")

    entry = store.get(name)
    return ok({
        "name": entry["name"],
        "type": entry["type"],
        "value": entry["value"],
        "source": entry.get("source", {}),
    })


def _handle_show(args: dict[str, Any]) -> dict:
    variables = store.show()
    if args.get("json"):
        return ok({"variables": store.to_dict(), "count": len(variables)})

    if not variables:
        return ok({"message": "没有存储的变量。", "count": 0})

    # 表格格式
    rows = []
    for v in variables:
        value_str = _format_value(v["value"], v["type"])
        rows.append({
            "name": v["name"],
            "type": v["type"],
            "value": value_str,
        })
    return ok({"variables": rows, "count": len(rows)})


def _handle_delete(args: dict[str, Any]) -> dict:
    positional = args.get("_", [])
    name = args.get("name", "")
    if not name and positional:
        name = str(positional[0])
    if not name:
        return fail("缺少变量名。用法: /var delete <name>")

    store.delete(name)
    return ok({"message": f"变量 '{name}' 已删除。"})


def _handle_clear(args: dict[str, Any]) -> dict:
    count = len(store._vars)
    store.clear()
    return ok({"message": f"已清空 {count} 个变量。"})


def _handle_export(args: dict[str, Any]) -> dict:
    filepath = args.get("file", "")
    if not filepath:
        return fail("缺少 --file。用法: /var export --file=<path.yaml>")

    count = store.export_yaml(filepath)
    return ok({
        "message": f"已导出 {count} 个变量至 {filepath}",
        "file": filepath,
        "count": count,
    })


def _handle_import(args: dict[str, Any]) -> dict:
    filepath = args.get("file", "")
    if not filepath:
        return fail("缺少 --file。用法: /var import --file=<path.yaml> [--mode=merge|replace]")

    mode = args.get("mode", "merge").strip().lower()
    if mode not in ("merge", "replace"):
        return fail(f"无效的导入模式 '{mode}'。可用: merge, replace")

    count = store.import_yaml(filepath, mode=mode)
    return ok({
        "message": f"已从 {filepath} 导入 {count} 个变量（模式: {mode}）",
        "file": filepath,
        "count": count,
        "mode": mode,
    })


# ── helpers ──────────────────────────────────────────────────────────────

def _format_value(value: Any, vtype: str) -> str:
    """格式化值用于表格展示。"""
    if vtype == "json":
        if isinstance(value, (dict, list)):
            import json
            text = json.dumps(value, ensure_ascii=False)
            if len(text) > 60:
                return text[:57] + "..."
            return text
        return str(value)
    if vtype == "boolean":
        return "true" if value else "false"
    return str(value)
