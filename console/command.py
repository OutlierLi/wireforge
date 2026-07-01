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
    module: str = ""    # "wireforge_serial.api"
    handler: str = ""   # "serial_open"
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    sub_commands: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "name": self.name, "desc": self.desc,
            "module": self.module, "handler": self.handler,
            "enabled": self.enabled, "params": self.params,
        }
        if self.sub_commands:
            d["sub_commands"] = self.sub_commands
        return d


class Registry:
    """命令注册表 — 从 JSON 加载，按名分发到业务模块。"""

    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._handler_cache: dict[str, Callable] = {}

    def load_file(self, path: str):
        """从单个 JSON 文件加载所有命令 (key=命令名, value=定义)。"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for name, entry in data.items():
            cmd = Command(
                name=name,
                desc=entry.get("desc", ""),
                module=entry.get("module", ""),
                handler=entry.get("handler", ""),
                enabled=entry.get("enabled", True),
                params=entry.get("params", {}),
                sub_commands=entry.get("sub_commands", {}),
            )
            self._commands[name] = cmd

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
