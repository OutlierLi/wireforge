"""VariableStore — 内存变量存储，支持 CRUD、类型校验、YAML 导入导出。

变量系统定位：
- 默认仅存在于当前 command-runtime 进程内存中。
- 不自动持久化。
- 不做敏感信息识别、脱敏或过滤。
- 变量系统不判断协议字段是否合法。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

# ── 类型定义 ────────────────────────────────────────────────────────────

VALID_TYPES = frozenset({"string", "integer", "decimal", "boolean", "hex", "json"})

# decimal: 数字、可选一个小数点、可选负号
_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
# hex: 仅允许十六进制字符和分隔符（空格、冒号、短横线）
_HEX_RE = re.compile(r"^[0-9a-fA-F \:\-]+$")
# 变量名
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ── 错误类型 ────────────────────────────────────────────────────────────

class VariableError(ValueError):
    """变量系统基础错误。"""
    code: str = "VARIABLE_ERROR"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


# ── 变量存储 ────────────────────────────────────────────────────────────

class VariableStore:
    """内存变量存储 — 全局单例。"""

    def __init__(self):
        self._vars: dict[str, dict[str, Any]] = {}

    # ── CRUD ─────────────────────────────────────────────────────────

    def set(self, name: str, value: Any, vtype: str = "string",
            source: dict[str, Any] | None = None) -> dict[str, Any]:
        """设置变量。校验类型后存入内存。返回存入的变量 dict。"""
        if not _NAME_RE.match(name):
            raise VariableError(
                f"变量名 '{name}' 非法。只允许字母、数字、下划线，且不能以数字开头。",
                code="VARIABLE_NAME_INVALID",
            )
        if vtype not in VALID_TYPES:
            raise VariableError(
                f"变量类型 '{vtype}' 不支持。支持的类型: {', '.join(sorted(VALID_TYPES))}",
                code="VARIABLE_TYPE_INVALID",
            )

        normalized = self._normalize(value, vtype)
        entry = {
            "name": name,
            "type": vtype,
            "value": normalized,
            "source": source or {"kind": "user"},
        }
        self._vars[name] = entry
        return entry

    def get(self, name: str) -> dict[str, Any]:
        """获取变量完整信息（含 type/value/source）。支持嵌套路径。"""
        root_name, *path = name.split(".", 1)
        entry = self._vars.get(root_name)
        if entry is None:
            raise VariableError(
                f"变量 '{root_name}' 不存在。",
                code="VARIABLE_NOT_FOUND",
            )
        if not path:
            return entry.copy()

        # 嵌套路径
        if entry["type"] != "json":
            raise VariableError(
                f"变量 '{root_name}' 不是 json 类型，无法访问嵌套字段 '{path[0]}'。",
                code="VARIABLE_PATH_NOT_FOUND",
            )
        return self._resolve_path(entry, path[0])

    def get_value(self, name: str) -> Any:
        """获取变量的值。支持嵌套路径。"""
        root_name, *path = name.split(".", 1)
        entry = self._vars.get(root_name)
        if entry is None:
            raise VariableError(
                f"变量 '{root_name}' 不存在。",
                code="VARIABLE_NOT_FOUND",
            )
        if not path:
            return entry["value"]

        if entry["type"] != "json":
            raise VariableError(
                f"变量 '{root_name}' 不是 json 类型，无法访问嵌套字段。",
                code="VARIABLE_PATH_NOT_FOUND",
            )
        return self._walk_json(entry["value"], path[0])

    def show(self) -> list[dict[str, Any]]:
        """返回所有变量的列表。"""
        return [entry.copy() for entry in self._vars.values()]

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """导出为 {name: {type, value}} 格式。"""
        return {name: {"type": e["type"], "value": e["value"]}
                for name, e in self._vars.items()}

    def delete(self, name: str) -> bool:
        """删除变量。返回是否成功删除。"""
        if name not in self._vars:
            raise VariableError(
                f"变量 '{name}' 不存在。",
                code="VARIABLE_NOT_FOUND",
            )
        del self._vars[name]
        return True

    def clear(self):
        """清空所有变量。"""
        self._vars.clear()

    # ── 导入导出 ─────────────────────────────────────────────────────

    def export_yaml(self, filepath: str) -> int:
        """导出变量为 YAML 文件（原子写入）。

        写入流程: 规范化 → .tmp → fsync → 原子 rename。
        返回导出的变量数量。
        """
        path = Path(filepath).resolve()
        tmp = path.with_suffix(path.suffix + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)

        doc = {
            "version": 1,
            "variables": self.to_dict(),
        }

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.safe_dump(doc, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(path))
        except OSError as e:
            raise VariableError(
                f"导出变量失败: {e}",
                code="VARIABLE_EXPORT_FAILED",
            )

        return len(self._vars)

    def import_yaml(self, filepath: str, mode: str = "merge") -> int:
        """从 YAML 文件导入变量。

        mode:
          - merge: YAML 中存在的变量覆盖，内存中 YAML 未包含的保留。
          - replace: 清空后加载 YAML 内全部变量。失败时不清空原内存。
        """
        path = Path(filepath).resolve()
        if not path.exists():
            raise VariableError(
                f"文件不存在: {filepath}",
                code="VARIABLE_IMPORT_FAILED",
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            raise VariableError(
                f"无法读取 YAML 文件: {e}",
                code="VARIABLE_IMPORT_FAILED",
            )

        if not isinstance(doc, dict) or "version" not in doc:
            raise VariableError(
                "YAML 格式不支持：缺少 version 字段。",
                code="VARIABLE_YAML_VERSION_UNSUPPORTED",
            )

        version = doc.get("version")
        if version != 1:
            raise VariableError(
                f"YAML 版本 {version} 不支持，仅支持 version=1。",
                code="VARIABLE_YAML_VERSION_UNSUPPORTED",
            )

        raw_vars = doc.get("variables", {})
        if not isinstance(raw_vars, dict):
            raise VariableError(
                "YAML 中 variables 字段格式非法。",
                code="VARIABLE_IMPORT_FAILED",
            )

        # 先校验所有变量，构造临时 store
        temp: dict[str, dict[str, Any]] = {}
        for name, entry in raw_vars.items():
            if not isinstance(entry, dict):
                raise VariableError(
                    f"YAML 中变量 '{name}' 格式非法：必须是包含 type/value 的字典。",
                    code="VARIABLE_IMPORT_FAILED",
                )
            vtype = entry.get("type", "string")
            value = entry.get("value")

            if not _NAME_RE.match(name):
                raise VariableError(
                    f"YAML 中变量名 '{name}' 非法。",
                    code="VARIABLE_NAME_INVALID",
                )
            if vtype not in VALID_TYPES:
                raise VariableError(
                    f"YAML 中变量 '{name}' 的类型 '{vtype}' 不支持。",
                    code="VARIABLE_TYPE_INVALID",
                )

            try:
                normalized = self._normalize(value, vtype)
            except VariableError as e:
                raise VariableError(
                    f"YAML 中变量 '{name}' 的 {vtype} 值非法: {e}",
                    code="VARIABLE_VALUE_INVALID",
                )

            temp[name] = {
                "name": name,
                "type": vtype,
                "value": normalized,
                "source": {"kind": "import", "file": str(path)},
            }

        # 一次性应用（原子语义）
        if mode == "replace":
            self._vars.clear()
        self._vars.update(temp)
        return len(temp)

    # ── 内部方法 ─────────────────────────────────────────────────────

    def _normalize(self, value: Any, vtype: str) -> Any:
        """校验并规范化值。"""
        if value is None:
            raise VariableError("变量值不能为 None。", code="VARIABLE_VALUE_INVALID")

        if vtype == "string":
            return str(value)

        elif vtype == "integer":
            try:
                return int(value)
            except (ValueError, TypeError):
                raise VariableError(
                    f"变量 integer 值非法：'{value}' 不是有效整数。",
                    code="VARIABLE_VALUE_INVALID",
                )

        elif vtype == "decimal":
            text = str(value).strip()
            if not _DECIMAL_RE.match(text):
                raise VariableError(
                    f"变量 decimal 值非法：'{value}'。",
                    code="VARIABLE_VALUE_INVALID",
                )
            return text

        elif vtype == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "1", "yes"):
                    return True
                if v in ("false", "0", "no"):
                    return False
            if isinstance(value, (int, float)):
                return bool(value)
            raise VariableError(
                f"变量 boolean 值非法：'{value}'。",
                code="VARIABLE_VALUE_INVALID",
            )

        elif vtype == "hex":
            text = str(value).strip()
            if not _HEX_RE.match(text):
                raise VariableError(
                    f"变量 hex 值包含非法字符：'{value}'。仅允许 0-9 A-F 和分隔符（空格、冒号、短横线）。",
                    code="VARIABLE_VALUE_INVALID",
                )
            # 规范化为大写、单空格分隔
            raw = re.sub(r"[\s\:\-]+", "", text).upper()
            if len(raw) % 2 != 0:
                raise VariableError(
                    f"变量 hex 值字节数不完整：'{value}'。每字节必须恰好两位。",
                    code="VARIABLE_VALUE_INVALID",
                )
            return " ".join(raw[i:i + 2] for i in range(0, len(raw), 2))

        elif vtype == "json":
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as e:
                    raise VariableError(
                        f"变量 json 值解析失败：{e}",
                        code="VARIABLE_VALUE_INVALID",
                    )
                if isinstance(parsed, (dict, list)):
                    return parsed
                # JSON 原始值（数字、字符串、布尔等）也允许
                return parsed
            # 数字、布尔等直接存
            return value

        raise VariableError(f"未知类型: {vtype}", code="VARIABLE_TYPE_INVALID")

    @staticmethod
    def _walk_json(value: Any, path: str) -> Any:
        """在 JSON 值中按点分隔路径逐层访问。"""
        parts = path.split(".")
        current = value
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    raise VariableError(
                        f"JSON 对象中不存在字段 '{part}'。",
                        code="VARIABLE_PATH_NOT_FOUND",
                    )
                current = current[part]
            else:
                raise VariableError(
                    f"无法在非对象值上访问字段 '{part}'。",
                    code="VARIABLE_PATH_NOT_FOUND",
                )
        return current

    @staticmethod
    def _resolve_path(entry: dict[str, Any], path: str) -> dict[str, Any]:
        """解析嵌套路径，返回叶子变量的完整信息。"""
        value = VariableStore._walk_json(entry["value"], path)
        # 返回叶子值的信息 — 类型继承自 root
        return {
            "name": f"{entry['name']}.{path}",
            "type": _infer_json_type(value),
            "value": value,
            "source": entry.get("source", {}),
        }


def _infer_json_type(value: Any) -> str:
    """推断 JSON 叶子值的变量类型。"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


# ── 全局单例 ────────────────────────────────────────────────────────────

store = VariableStore()
