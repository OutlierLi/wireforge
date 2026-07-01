#!/usr/bin/env python3
"""从现有 console/commands.json 生成完整命令树结构并写回。

树形约定:
  - 顶层 params 为空 {}
  - 参数定义在 sub_commands.<sub>.params
  - 保留 module / handler / enabled
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMMANDS_JSON = ROOT / "console" / "commands.json"

# 单子命令默认 sub 名（与 console/command_schema.DEFAULT_SUB 一致）
DEFAULT_SUB: dict[str, str] = {
    "decode": "decode",
    "route": "resolve",
    "find": "search",
    "delay": "wait",
    "print": "text",
    "help": "show",
    "split": "open",
    "run": "execute",
    "upg": "transfer",
    "wait-frame": "listen",
    "request": "send",
    "build": "build",
    "serial": "ports",
    "auto_rule": "list",
}


def _p(**kwargs: Any) -> dict[str, Any]:
    return kwargs


def _sub(desc: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"desc": desc, "params": params or {}}


def _base(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "desc": entry["desc"],
        "module": entry["module"],
        "handler": entry["handler"],
        "enabled": entry.get("enabled", True),
        "params": {},
    }


def _single_sub(entry: dict[str, Any], sub_name: str, sub_desc: str | None = None) -> dict[str, Any]:
    """将顶层 params 移入唯一子命令。"""
    out = _base(entry)
    raw_params = {
        k: deepcopy(v)
        for k, v in entry.get("params", {}).items()
        if k not in ("sub",)
    }
    out["sub_commands"] = {
        sub_name: _sub(sub_desc or entry["desc"], raw_params),
    }
    return out


def _build_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    build_params = {
        "proto": _p(
            type="choice",
            required=True,
            order=1,
            desc="协议类型",
            examples=["dlt645", "csg"],
        ),
        "func": _p(
            type="hex",
            required=False,
            desc="功能码 (DLT645)",
            examples=["0x11", "0x13"],
        ),
        "afn": _p(
            type="hex",
            required=False,
            desc="应用功能码 (CSG)",
            examples=["0x00", "0x03"],
        ),
        "di": _p(
            type="str",
            required=False,
            desc="数据标识DI",
            examples=["00010000", "E8020701"],
        ),
        "dir": _p(
            type="choice",
            required=False,
            desc="传输方向",
            examples=["downlink", "uplink"],
            default="downlink",
        ),
        "set": _p(
            type="str",
            required=False,
            desc="设置/覆盖字段值",
            examples=["di=00020000", "freeze_year=26"],
        ),
        "*": _p(
            type="dynamic",
            required=False,
            desc="业务字段由 resolve 后动态决定",
        ),
    }
    resolve_params = {
        "proto": _p(
            type="choice",
            required=True,
            order=1,
            desc="协议类型",
            examples=["dlt645", "csg"],
        ),
        "func": _p(
            type="hex",
            required=False,
            desc="功能码 (DLT645)",
            examples=["0x11", "0x13"],
        ),
        "afn": _p(
            type="hex",
            required=False,
            desc="应用功能码 (CSG)",
            examples=["0x00", "0x03"],
        ),
        "di": _p(
            type="str",
            required=False,
            desc="数据标识DI",
            examples=["00010000", "E8020701"],
        ),
        "dir": _p(
            type="choice",
            required=False,
            desc="传输方向",
            examples=["downlink", "uplink"],
            default="downlink",
        ),
    }
    from_frame_params = {
        "from_frame": _p(
            type="str",
            required=True,
            order=1,
            desc="从已有 hex 报文解码后修改字段再重建",
            examples=["FE FE 68 ... 16"],
        ),
        "set": _p(
            type="str",
            required=False,
            desc="设置/覆盖字段值",
            examples=["di=00020000", "freeze_year=26"],
        ),
        "proto": _p(
            type="choice",
            required=False,
            desc="协议类型（省略则自动检测）",
            examples=["dlt645", "csg"],
        ),
    }
    out["sub_commands"] = {
        "build": _sub(
            "Build protocol frame from target info",
            build_params,
        ),
        "from-frame": _sub(
            "Rebuild frame from existing hex, optionally modify fields",
            from_frame_params,
        ),
        "resolve": _sub(
            "Resolve target only, return input_schema without building frame",
            resolve_params,
        ),
    }
    return out


def _decode_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "decode": _sub(
            entry["desc"],
            {
                "proto": _p(
                    type="choice",
                    required=True,
                    order=1,
                    desc="协议类型",
                    examples=["dlt645", "csg"],
                ),
                "hex": _p(
                    type="str",
                    required=True,
                    order=2,
                    desc="十六进制报文字节流",
                    examples=[
                        "FE FE 68 ... 16",
                        "68 0C 00 40 03 01 01 03 00 E8 30 16",
                    ],
                ),
            },
        ),
    }
    return out


def _route_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "resolve": _sub(
            entry["desc"],
            {
                "proto": _p(
                    type="choice",
                    required=True,
                    order=1,
                    desc="协议类型",
                    examples=["dlt645", "csg"],
                ),
                "func": _p(
                    type="hex",
                    required=False,
                    desc="功能码 (DLT645)",
                    examples=["0x11", "0x13"],
                ),
                "afn": _p(
                    type="hex",
                    required=False,
                    desc="应用功能码 (CSG)",
                    examples=["0x00", "0x06"],
                ),
                "di": _p(
                    type="str",
                    required=False,
                    desc="数据标识DI",
                    examples=["00010000", "E8010601"],
                ),
                "dir": _p(
                    type="choice",
                    required=False,
                    desc="传输方向",
                    examples=["downlink", "uplink"],
                    default="downlink",
                ),
            },
        ),
    }
    return out


def _find_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "search": _sub(
            entry["desc"],
            {
                "proto": _p(
                    type="choice",
                    required=False,
                    desc="协议类型（不指定则搜索全部）",
                    examples=["dlt645", "csg"],
                ),
                "meaning": _p(
                    type="str",
                    required=False,
                    desc="全文模糊搜索关键词",
                    examples=["初始化", "查询"],
                ),
                "filter": _p(
                    type="str",
                    required=False,
                    desc="额外 AND 过滤条件，可多次使用",
                    examples=["档案", "uplink", "心跳"],
                ),
                "di": _p(
                    type="str",
                    required=False,
                    desc="按 DI 精确匹配",
                    examples=["E8020102", "00010000"],
                ),
                "afn": _p(
                    type="hex",
                    required=False,
                    desc="按 AFN 精确匹配（CSG）",
                    examples=["0x01", "0x06"],
                ),
                "func": _p(
                    type="hex",
                    required=False,
                    desc="按功能码精确匹配（DLT645）",
                    examples=["0x11", "0x13"],
                ),
                "dir": _p(
                    type="choice",
                    required=False,
                    desc="按传输方向过滤",
                    examples=["downlink", "uplink"],
                ),
            },
        ),
    }
    return out


def _delay_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "wait": _sub(
            entry["desc"],
            {
                "value": _p(
                    type="str",
                    required=True,
                    desc="时长，默认 ms，支持 s 后缀",
                    examples=["100", "500ms", "2s", "1.5s"],
                ),
            },
        ),
    }
    return out


def _print_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "text": _sub(
            entry["desc"],
            {
                "text": _p(
                    type="str",
                    required=True,
                    desc="文本内容，支持 ${name} 变量引用和 ${object.field} 路径访问",
                    examples=[
                        "当前协议：${protocol}",
                        "${frame}",
                        "AFN=${afn}",
                    ],
                ),
                "raw": _p(
                    type="bool",
                    required=False,
                    desc="原样输出，不解析变量引用",
                ),
            },
        ),
    }
    return out


def _help_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "show": _sub(
            entry["desc"],
            {
                "target": _p(
                    type="str",
                    required=False,
                    desc="Command name, e.g. /serial",
                    examples=["/serial", "/serial open"],
                ),
            },
        ),
    }
    return out


def _split_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "open": _sub(
            entry["desc"],
            {
                "mode": _p(
                    type="choice",
                    required=False,
                    desc="启动模式",
                    examples=["split", "tab", "window"],
                    default="tab",
                ),
                "dry-run": _p(
                    type="bool",
                    required=False,
                    desc="仅打印启动命令，不实际执行",
                ),
            },
        ),
    }
    return out


def _run_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "execute": _sub(
            entry["desc"],
            {
                "file": _p(
                    type="str",
                    required=True,
                    desc="TestPlan YAML file",
                    examples=["tests/sta_join.yaml"],
                ),
                "dry-run": _p(
                    type="bool",
                    required=False,
                    desc="Resolve and report steps without executing serial/protocol commands",
                ),
                "json": _p(
                    type="bool",
                    required=False,
                    desc="Reserved for structured clients; command response is always structured",
                ),
                "var": _p(
                    type="str",
                    required=False,
                    desc="Override plan variable; may be repeated",
                    examples=["cco=COM9", "sta=COM10"],
                ),
                "timeout": _p(
                    type="int",
                    required=False,
                    desc="Override total run timeout in ms",
                    examples=[120000],
                ),
                "report": _p(
                    type="str",
                    required=False,
                    desc="Report output directory",
                    examples=["reports/sta_join_001"],
                ),
            },
        ),
    }
    return out


def _upg_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "transfer": _sub(
            entry["desc"],
            {
                "file": _p(
                    type="str",
                    required=True,
                    order=1,
                    desc="Firmware file path (quotes and database/bin relative paths supported)",
                    examples=[
                        "database/bin/firmware_v2.bin",
                        '"/path/with spaces/fw.bin"',
                    ],
                ),
                "proto": _p(
                    type="str",
                    required=False,
                    desc="Protocol (default csg; aliases csg2016, csg_2016)",
                    examples=["csg", "csg2016"],
                    default="csg",
                ),
                "segment-size": _p(
                    type="int",
                    required=False,
                    desc="Segment size (128/256/512/1024)",
                    examples=[1024, 512],
                    default=1024,
                ),
                "file-type": _p(
                    type="int",
                    required=False,
                    desc="File type (0=clear, 1=CCO module, 2=slave module, 3=collector)",
                    examples=[1, 2],
                    default=1,
                ),
                "file-id": _p(
                    type="int",
                    required=False,
                    desc="File ID",
                    examples=[1],
                    default=1,
                ),
                "dest": _p(
                    type="str",
                    required=False,
                    desc="Destination address",
                    examples=["999999999999"],
                    default="999999999999",
                ),
                "timeout-min": _p(
                    type="int",
                    required=False,
                    desc="File transfer timeout in minutes",
                    examples=[30],
                    default=30,
                ),
                "ack-timeout": _p(
                    type="str",
                    required=False,
                    desc="Per-segment ACK timeout (e.g. 5s, 500ms); alias: timeout",
                    examples=["5s", "10s"],
                    default="5s",
                ),
                "timeout": _p(
                    type="str",
                    required=False,
                    desc="Alias for ack-timeout",
                    examples=["5s"],
                ),
                "final-ack-timeout": _p(
                    type="str",
                    required=False,
                    desc="Final segment ACK timeout",
                    examples=["30s"],
                    default="30s",
                ),
                "interval": _p(
                    type="str",
                    required=False,
                    desc="Inter-frame delay",
                    examples=["0ms", "100ms"],
                    default="0",
                ),
                "ack-wait": _p(
                    type="str",
                    required=False,
                    desc="ACK wait_time handling: ignore or respect",
                    examples=["ignore", "respect"],
                    default="ignore",
                ),
                "resume": _p(
                    type="bool",
                    required=False,
                    desc="Enable resume from E8000703 query",
                    default=True,
                ),
                "no-resume": _p(
                    type="bool",
                    required=False,
                    desc="Disable resume",
                ),
                "clear": _p(
                    type="str",
                    required=False,
                    desc="Clear mode: auto, always, never",
                    examples=["auto", "always", "never"],
                    default="auto",
                ),
                "finish": _p(
                    type="str",
                    required=False,
                    desc="Finish mode: none, progress, report",
                    examples=["none", "progress", "report"],
                    default="none",
                ),
                "finish-timeout": _p(
                    type="str",
                    required=False,
                    desc="Finish progress poll timeout",
                    examples=["60s"],
                    default="60s",
                ),
                "seq": _p(
                    type="int",
                    required=False,
                    desc="Starting SEQ value",
                    examples=[1],
                    default=1,
                ),
                "retries": _p(
                    type="int",
                    required=False,
                    desc="Retries per segment",
                    examples=[3],
                    default=3,
                ),
                "to": _p(
                    type="str",
                    required=False,
                    desc="Serial connection name; omitted when exactly one connection is active",
                    examples=["cco"],
                ),
                "no-cache": _p(
                    type="bool",
                    required=False,
                    desc="Force rebuild .upg_cache",
                ),
                "build-only": _p(
                    type="bool",
                    required=False,
                    desc="Only build/validate cache, do not transfer",
                ),
            },
        ),
    }
    return out


def _wait_frame_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "listen": _sub(
            entry["desc"],
            {
                "name": _p(
                    type="str",
                    required=False,
                    recommended=True,
                    desc="Serial connection name",
                    examples=["default", "cco"],
                ),
                "timeout": _p(
                    type="int",
                    required=False,
                    desc="Max wait time in ms",
                    examples=[5000, 10000],
                    default=5000,
                ),
                "proto": _p(
                    type="choice",
                    required=False,
                    desc="Protocol to decode (auto-detect if omitted)",
                    examples=["csg", "dlt645"],
                ),
                "expect.afn": _p(type="str", required=False, desc="Expected AFN value"),
                "expect.di": _p(type="str", required=False, desc="Expected DI value"),
                "expect.dir": _p(
                    type="choice",
                    required=False,
                    desc="Expected direction",
                    examples=["uplink", "downlink"],
                ),
                "expect": _p(
                    type="str",
                    required=False,
                    desc='Full expect JSON: {"all":[{"path":"$.afn","op":"eq","value":"04"}]}',
                ),
                "*": _p(
                    type="dynamic",
                    required=False,
                    desc="Additional expect paths: --expect.user_data.result=success",
                ),
            },
        ),
    }
    return out


def _request_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "send": _sub(
            entry["desc"],
            {
                "send": _p(
                    type="str",
                    required=True,
                    order=1,
                    desc="Hex frame to send",
                    examples=["68 0C 00 40 03 01 01 03 00 E8 30 16"],
                ),
                "name": _p(
                    type="str",
                    required=False,
                    recommended=True,
                    desc="Serial connection name",
                    examples=["default", "cco"],
                ),
                "timeout": _p(
                    type="int",
                    required=False,
                    desc="Max wait time in ms",
                    examples=[3000, 5000],
                    default=5000,
                ),
                "proto": _p(
                    type="choice",
                    required=False,
                    desc="Protocol for decode (auto-detect if omitted)",
                    examples=["csg", "dlt645"],
                ),
                "wait.afn": _p(type="str", required=False, desc="Expected AFN in response"),
                "wait.di": _p(type="str", required=False, desc="Expected DI in response"),
                "wait.dir": _p(
                    type="choice",
                    required=False,
                    desc="Expected direction in response",
                    examples=["uplink", "downlink"],
                ),
                "*": _p(
                    type="dynamic",
                    required=False,
                    desc="Additional wait paths: --wait.user_data.result=success",
                ),
            },
        ),
    }
    return out


def _auto_rule_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    common_rule_fields = {
        "match": _p(type="str", required=False, desc="正则匹配模式 (regex)"),
        "name": _p(type="str", required=False, desc="规则名称"),
        "source": _p(type="str", required=False, desc="触发源 serial:default"),
        "then": _p(type="str", required=False, desc="匹配后执行的命令"),
    }
    out["sub_commands"] = {
        "add": _sub(
            "Add a new rule with match condition and actions",
            {
                **common_rule_fields,
                "id": _p(type="str", required=False, desc="规则ID（省略则自动生成）"),
            },
        ),
        "list": _sub("List all registered rules", {}),
        "show": _sub(
            "Show full details of a rule by id",
            {"id": _p(type="str", required=True, desc="规则ID")},
        ),
        "enable": _sub(
            "Enable a disabled rule",
            {"id": _p(type="str", required=True, desc="规则ID")},
        ),
        "disable": _sub(
            "Disable a rule without deleting",
            {"id": _p(type="str", required=True, desc="规则ID")},
        ),
        "delete": _sub(
            "Permanently remove a rule",
            {"id": _p(type="str", required=True, desc="规则ID")},
        ),
        "test": _sub(
            "Test a rule against a hex frame (dry-run)",
            {
                "id": _p(type="str", required=True, order=1, desc="规则ID"),
                "hex": _p(
                    type="str",
                    required=True,
                    order=2,
                    desc="测试用十六进制报文",
                ),
            },
        ),
        "load": _sub(
            "Load rules from YAML file",
            {"file": _p(type="str", required=True, desc="YAML规则文件路径")},
        ),
        "history": _sub(
            "Show rule match history, optionally filtered by id",
            {"id": _p(type="str", required=False, desc="规则ID（可选过滤）")},
        ),
    }
    return out


def _var_command(entry: dict[str, Any]) -> dict[str, Any]:
    out = _base(entry)
    out["sub_commands"] = {
        "set": _sub(
            "Set a variable: /var set <name> --value=<value> [--type=<type>]",
            {
                "name": _p(
                    type="str",
                    required=False,
                    recommended=True,
                    positional=True,
                    order=0,
                    desc="变量名",
                ),
                "value": _p(type="str", required=True, desc="变量值"),
                "type": _p(
                    type="choice",
                    required=False,
                    desc="变量类型",
                    examples=["string", "integer", "decimal", "boolean", "hex", "json"],
                    default="string",
                ),
            },
        ),
        "get": _sub(
            "Get a variable value: /var get <name>",
            {
                "name": _p(
                    type="str",
                    required=False,
                    recommended=True,
                    positional=True,
                    order=0,
                    desc="变量名",
                ),
            },
        ),
        "show": _sub(
            "Show all variables (table or --json)",
            {
                "json": _p(type="bool", required=False, desc="以 JSON 格式输出"),
            },
        ),
        "delete": _sub(
            "Delete a variable: /var delete <name>",
            {
                "name": _p(
                    type="str",
                    required=False,
                    recommended=True,
                    positional=True,
                    order=0,
                    desc="变量名",
                ),
            },
        ),
        "clear": _sub("Clear all variables", {}),
        "export": _sub(
            "Export variables to YAML: /var export --file=<path.yaml>",
            {"file": _p(type="str", required=True, desc="YAML文件路径")},
        ),
        "import": _sub(
            "Import variables from YAML: /var import --file=<path.yaml> [--mode=merge|replace]",
            {
                "file": _p(type="str", required=True, desc="YAML文件路径"),
                "mode": _p(
                    type="choice",
                    required=False,
                    desc="导入模式",
                    examples=["merge", "replace"],
                    default="merge",
                ),
            },
        ),
    }
    return out


def _serial_command(entry: dict[str, Any]) -> dict[str, Any]:
    """serial 已是树形结构，保留 module/handler/enabled/desc，深拷贝 sub_commands。"""
    out = _base(entry)
    out["sub_commands"] = deepcopy(entry.get("sub_commands", {}))
    return out


BUILDERS: dict[str, Any] = {
    "build": _build_command,
    "decode": _decode_command,
    "route": _route_command,
    "find": _find_command,
    "delay": _delay_command,
    "print": _print_command,
    "help": _help_command,
    "split": _split_command,
    "run": _run_command,
    "upg": _upg_command,
    "wait-frame": _wait_frame_command,
    "request": _request_command,
    "auto_rule": _auto_rule_command,
    "var": _var_command,
    "serial": _serial_command,
}


def build_commands_tree(existing: dict[str, Any]) -> dict[str, Any]:
    expected = set(BUILDERS.keys())
    missing = expected - set(existing.keys())
    if missing:
        raise SystemExit(f"missing commands in source JSON: {sorted(missing)}")

    out: dict[str, Any] = {}
    for name in sorted(BUILDERS.keys()):
        out[name] = BUILDERS[name](existing[name])
    return out


def main() -> None:
    existing = json.loads(COMMANDS_JSON.read_text(encoding="utf-8"))
    tree = build_commands_tree(existing)
    COMMANDS_JSON.write_text(
        json.dumps(tree, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    line_count = len(COMMANDS_JSON.read_text(encoding="utf-8").splitlines())
    print(f"wrote {COMMANDS_JSON} ({line_count} lines, {len(tree)} commands)")


if __name__ == "__main__":
    main()
