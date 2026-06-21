"""命令定义 — 纯数据结构，描述接口契约。

每个命令定义: 名称、描述、参数列表、是否启用、超时。

参数: {name, type, required, desc, values, default}
  类型: str | int | hex | bool | choice
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ParamType = Literal["str", "int", "hex", "bool", "choice"]


@dataclass
class Param:
    """命令参数定义。"""
    name: str
    type: ParamType = "str"
    required: bool = False
    desc: str = ""
    values: list[str] | None = None   # choice 类型的可选值
    default: Any = None

    def to_dict(self) -> dict:
        d = {"name": self.name, "type": self.type, "required": self.required}
        if self.desc: d["desc"] = self.desc
        if self.values: d["values"] = self.values
        if self.default is not None: d["default"] = self.default
        return d

    def validate(self, value: Any) -> str | None:
        """校验参数值，返回错误信息或 None。"""
        if value is None:
            if self.required:
                return f"{self.name}: required"
            return None
        if self.type == "str":
            if not isinstance(value, str):
                return f"{self.name}: expected str"
        elif self.type == "int":
            try:
                int(value)
            except (ValueError, TypeError):
                return f"{self.name}: expected int"
        elif self.type == "hex":
            if isinstance(value, str):
                try:
                    int(value.replace("0x", "").replace("0X", ""), 16)
                except ValueError:
                    return f"{self.name}: invalid hex: {value}"
            elif not isinstance(value, int):
                return f"{self.name}: expected hex string or int"
        elif self.type == "bool":
            if value not in (True, False, "true", "false"):
                return f"{self.name}: expected bool"
        elif self.type == "choice":
            if self.values and str(value) not in self.values:
                return f"{self.name}: must be one of {self.values}"
        return None


@dataclass
class Command:
    """命令定义。"""
    name: str
    desc: str = ""
    params: list[Param] = field(default_factory=list)
    enabled: bool = True
    timeout: int = 15000  # ms

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "desc": self.desc,
            "params": [p.to_dict() for p in self.params],
            "enabled": self.enabled,
            "timeout": self.timeout,
        }


class Registry:
    """命令注册表。"""

    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._handlers: dict[str, Callable] = {}

    def register(self, cmd: Command, handler: Callable) -> None:
        self._commands[cmd.name] = cmd
        self._handlers[cmd.name] = handler

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def handler(self, name: str) -> Callable | None:
        return self._handlers.get(name)

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    def all_commands(self) -> list[Command]:
        return [self._commands[n] for n in sorted(self._commands.keys())]

    def validate_args(self, name: str, args: dict[str, Any]) -> list[str]:
        """校验参数，返回错误列表。"""
        cmd = self._commands.get(name)
        if not cmd:
            return [f"unknown command: {name}"]
        errors = []
        for p in cmd.params:
            err = p.validate(args.get(p.name))
            if err:
                errors.append(err)
        return errors


# 全局单例
registry = Registry()
