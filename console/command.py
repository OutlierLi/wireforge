"""命令行注册表 — 从 JSON 文件加载，不做业务逻辑。

JSON 格式:
  {
    "name": "build",
    "desc": "构造协议报文",
    "module": "console.handler",
    "handler": "handle_build"
  }

命令行模块只做分发:  命令名 → import module → call handler(args) → return result
业务模块返回 dict:  {success, error, data, detail, ...}
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Command:
    name: str
    desc: str = ""
    module: str = ""    # "serial.api"
    handler: str = ""   # "serial_open"
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name, "desc": self.desc,
            "module": self.module, "handler": self.handler,
            "enabled": self.enabled,
        }


class Registry:
    """命令注册表 — 从 JSON 加载，按名分发到业务模块。"""

    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._handler_cache: dict[str, Callable] = {}

    def load_dir(self, path: str):
        """扫描目录下所有 .json 文件并注册。"""
        for fpath in sorted(Path(path).glob("*.json")):
            data = json.loads(fpath.read_text())
            cmd = Command(
                name=data["name"],
                desc=data.get("desc", ""),
                module=data.get("module", ""),
                handler=data.get("handler", ""),
                enabled=data.get("enabled", True),
            )
            self._commands[cmd.name] = cmd

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def resolve(self, name: str) -> Callable | None:
        """懒加载业务模块并返回 handler 函数。"""
        if name in self._handler_cache:
            return self._handler_cache[name]
        cmd = self._commands.get(name)
        if not cmd or not cmd.module or not cmd.handler:
            return None
        try:
            mod = importlib.import_module(cmd.module)
            fn = getattr(mod, cmd.handler)
            self._handler_cache[name] = fn
            return fn
        except Exception:
            return None

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    def all_commands(self) -> list[Command]:
        return [self._commands[n] for n in sorted(self._commands.keys())]


# 全局单例
registry = Registry()
