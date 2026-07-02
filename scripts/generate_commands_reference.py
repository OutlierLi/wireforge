#!/usr/bin/env python3
"""从 console/commands.json 生成命令参考 Markdown。"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from console.command_schema import format_usage_params, sorted_params

COMMANDS_JSON = ROOT / "console" / "commands.json"
OUTPUT = ROOT / "database" / "examples" / "COMMANDS_REFERENCE.md"

_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")


COMMAND_ZH: dict[str, str] = {
    "build": "根据协议目标构造报文帧",
    "decode": "将十六进制报文解码为结构化字段与路由路径",
    "route": "解析协议路由路径与 input_schema（/build 前置步骤）",
    "find": "按关键词、DI、AFN、功能码或方向搜索协议报文",
    "delay": "延时等待，支持毫秒或 s 后缀",
    "serial": "串口连接管理：连接、发送、关闭、列举端口等",
    "wait-frame": "监听串口，拆帧解码并按 expect 条件匹配响应",
    "request": "发送报文并等待匹配响应（自动化测试原语）",
    "run": "执行 YAML TestPlan 编排测试",
    "upg": "CSG AFN=07 固件文件传输/升级",
    "auto_rule": "mock://auto 自动应答规则引擎",
    "var": "会话变量管理（set/get/export 等）",
    "print": "打印文本，支持 ${变量} 插值",
    "help": "查看命令与子命令帮助",
}

SUB_ZH: dict[str, dict[str, str]] = {
    "build": {
        "build": "根据 proto/afn/di 等构造报文",
        "from-frame": "从已有 hex 报文修改字段后重建",
        "resolve": "仅解析目标，返回 input_schema",
    },
    "decode": {"decode": "解码十六进制报文"},
    "route": {"resolve": "解析路由与 input_schema"},
    "find": {"search": "搜索协议报文条目"},
    "delay": {"wait": "延时等待"},
    "print": {"text": "打印文本"},
    "help": {"show": "显示命令帮助"},
    "run": {"execute": "执行 TestPlan"},
    "upg": {"transfer": "固件文件传输"},
    "wait-frame": {"listen": "等待并匹配串口帧"},
    "request": {"send": "发送并等待匹配响应"},
    "serial": {
        "connect": "首次连接，必须指定 port",
        "open": "用上次参数重新打开连接",
        "close": "关闭指定连接",
        "disconnect": "close 的别名",
        "send": "仅发送十六进制帧",
        "set": "修改串口参数（下次 open 生效）",
        "ports": "列出可用串口与当前连接状态",
        "list": "ports 的别名",
    },
    "auto_rule": {
        "add": "新增自动应答规则",
        "update": "更新已有规则",
        "list": "列出所有规则",
        "show": "查看规则详情",
        "enable": "启用规则",
        "disable": "禁用规则",
        "delete": "删除规则",
        "test": "用 hex 报文 dry-run 测试规则",
        "load": "从 YAML 加载规则",
        "history": "查看规则匹配历史",
    },
    "var": {
        "set": "设置变量",
        "get": "读取变量",
        "show": "显示全部变量",
        "delete": "删除变量",
        "clear": "清空全部变量",
        "export": "导出变量到 YAML",
        "import": "从 YAML 导入变量",
    },
}


def _zh_desc(cmd_name: str, meta_desc: str, *, sub: str = "") -> str:
    if _HAS_CJK.search(meta_desc or ""):
        return meta_desc.strip()
    if sub and cmd_name in SUB_ZH and sub in SUB_ZH[cmd_name]:
        return SUB_ZH[cmd_name][sub]
    return COMMAND_ZH.get(cmd_name, meta_desc.strip())


def _bracket_label(meta: dict) -> str:
    if meta.get("required"):
        return "必填"
    if meta.get("recommended"):
        return "推荐"
    return "可选"


def _sub_entry(raw) -> dict:
    if isinstance(raw, str):
        return {"desc": raw, "params": {}}
    if isinstance(raw, dict):
        return raw
    return {"desc": "", "params": {}}


def _effective_params(entry: dict, sub_name: str | None) -> dict:
    base = {
        k: v for k, v in entry.get("params", {}).items()
        if k not in ("sub", "*") and isinstance(v, dict)
    }
    if not sub_name:
        return base
    sub = _sub_entry(entry.get("sub_commands", {}).get(sub_name, {}))
    merged = dict(base)
    for k, v in (sub.get("params") or {}).items():
        if isinstance(v, dict):
            merged[k] = v
    return merged


def _param_rows(params: dict[str, dict]) -> list[str]:
    rows: list[str] = []
    for key, meta in sorted_params(params):
        ptype = meta.get("type", "str")
        label = _bracket_label(meta)
        desc = meta.get("desc", "")
        default = meta.get("default", "")
        note = meta.get("note", "")
        examples = meta.get("examples", [])
        ex = "、".join(str(e) for e in examples[:4]) if examples else ""
        extra = []
        if default != "" and default is not None:
            extra.append(f"默认 `{default}`")
        if note:
            extra.append(note)
        if ex:
            extra.append(f"示例 {ex}")
        detail = "；".join([desc] + extra) if desc or extra else ""
        display_key = key if meta.get("positional") else key
        rows.append(f"| `{display_key}` | {label} | {ptype} | {detail} |")
    return rows


def _render_command(name: str, entry: dict) -> list[str]:
    lines: list[str] = []
    desc = _zh_desc(name, entry.get("desc", ""))
    lines.append(f"## /{name}")
    lines.append("")
    lines.append(f"**功能**：{desc}")
    lines.append("")

    subs = entry.get("sub_commands") or {}
    if not subs:
        return lines

    lines.append("### 子命令")
    lines.append("")

    for sub_name, raw in subs.items():
        sub = _sub_entry(raw)
        sub_desc = _zh_desc(name, sub.get("desc", ""), sub=sub_name)
        params = _effective_params(entry, sub_name)
        usage_suffix = format_usage_params(params)

        lines.append(f"#### `/{name} {sub_name}`")
        lines.append("")
        lines.append(f"**功能**：{sub_desc}")
        lines.append("")
        if usage_suffix:
            lines.append(f"**用法**：`/{name} {sub_name} {usage_suffix}`")
        else:
            lines.append(f"**用法**：`/{name} {sub_name}`")

        if params:
            lines.append("")
            lines.append("| 参数 | 必填/可选 | 类型 | 说明 |")
            lines.append("|------|-----------|------|------|")
            lines.extend(_param_rows(params))
        lines.append("")

    return lines


def generate() -> str:
    data = json.loads(COMMANDS_JSON.read_text(encoding="utf-8"))
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

    out: list[str] = [
        "# WireForge 命令参考",
        "",
        f"> 自动生成于 {ts}；源文件 [`console/commands.json`](../../console/commands.json)。",
        "> 重新生成：`python3 scripts/generate_commands_reference.py`",
        "",
        "## 符号说明",
        "",
        "| 写法 | 含义 |",
        "|------|------|",
        "| `<参数>` | **必填** |",
        "| `〔参数〕` | **可选，建议指定** |",
        "| `[参数]` | **可选** |",
        "",
        "参数在用法行与下表中按 **必填 → 推荐 → 可选** 排序。",
        "",
        "### 十六进制参数（`hex` / `from_frame` 等）",
        "",
        "命令行文本支持以下写法（空格可有可无）：",
        "",
        "- 连续 hex：`--hex=680C00400301010300E83016`",
        "- 带空格 + 引号：`--hex \"68 0C 00 40 03 01 01 03 00 E8 30 16\"`",
        "- 等号 + 引号：`--hex=\"68 0C 00 40 03 01 01 03 00 E8 30 16\"`",
        "- 无引号多 token：`--hex 68 0C 00 40 03 01 01 03 00 E8 30 16`",
        "",
        "JSON/API 调用直接传字符串即可，例如 `{\"hex\": \"68 0C ...\"}`。",
        "",
        "---",
        "",
    ]

    for name in sorted(data.keys()):
        entry = data[name]
        if not entry.get("enabled", True):
            continue
        out.extend(_render_command(name, entry))
        out.append("---")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generate(), encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
