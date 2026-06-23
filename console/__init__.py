"""WireForge 命令行接口 — 命令注册表 + 分发 API。"""
from pathlib import Path
from console.command import registry
from console.api import exec_cmd, list_cmds, get_cmd

# 启动时加载所有命令 JSON
_cmds_dir = Path(__file__).resolve().parent / "commands"
registry.load_dir(str(_cmds_dir))
