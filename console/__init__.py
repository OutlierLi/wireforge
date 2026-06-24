"""WireForge 命令行接口 — 命令注册表 + 分发 API。"""
from pathlib import Path
from console.command import registry
from console.api import exec_cmd, list_cmds, get_cmd

# 启动时加载命令 JSON
_cmds_file = Path(__file__).resolve().parent / "commands.json"
registry.load_file(str(_cmds_file))
