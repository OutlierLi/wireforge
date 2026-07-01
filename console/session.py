"""会话状态导出与恢复 — 支持 /split 终端分屏的状态继承。

导出内容:
  - 变量 (VariableStore)
  - 自动回复规则 (auto_rule._rules)
  - 串口连接设置 (serial_cmd._last_settings)

YAML 格式:
  version: 1
  variables: {name: {type, value}, ...}
  auto_rules: [{id, enabled, trigger, condition, actions, execution}, ...]
  serial_settings: {name: {port, baudrate, ...}, ...}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SESSION_VERSION = 1


def export_session(path: Path) -> Path:
    """导出完整会话状态到 YAML 文件，返回文件路径。

    导出的状态包括:
      - variables: 来自 VariableStore.to_dict()
      - auto_rules: 来自 console.handlers.auto_rule._rules
      - serial_settings: 来自 console.handlers.serial_cmd._last_settings
    """
    from console.variable_store import store as var_store

    payload: dict[str, Any] = {
        "version": SESSION_VERSION,
        "variables": var_store.to_dict(),
    }

    # 导出 auto_rules
    try:
        from console.handlers.auto_rule import _rules
        if _rules:
            payload["auto_rules"] = list(_rules.values())
    except ImportError:
        pass

    # 导出串口设置
    try:
        from console.handlers.serial_cmd import _last_settings
        if _last_settings:
            payload["serial_settings"] = dict(_last_settings)
    except ImportError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    return path


def restore_session(path: Path) -> dict[str, Any]:
    """从 YAML 文件恢复会话状态，返回恢复摘要。

    返回值:
      {variables_count, rules_count, settings_count, errors: [...]}
    """
    from console.variable_store import store as var_store

    summary: dict[str, Any] = {
        "variables_count": 0,
        "rules_count": 0,
        "settings_count": 0,
        "errors": [],
    }

    if not path.exists():
        summary["errors"].append(f"state file not found: {path}")
        return summary

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
    except Exception as e:
        summary["errors"].append(f"failed to load state: {e}")
        return summary

    if not isinstance(payload, dict):
        summary["errors"].append("state file must be a YAML object")
        return summary

    # 恢复变量
    variables = payload.get("variables", {})
    if isinstance(variables, dict):
        for name, entry in variables.items():
            if isinstance(entry, dict):
                vtype = entry.get("type", "string")
                value = entry.get("value")
                try:
                    var_store.set(name, value, vtype, source={
                        "kind": "restore", "file": str(path),
                    })
                    summary["variables_count"] += 1
                except Exception as e:
                    summary["errors"].append(f"variable {name}: {e}")

    # 恢复 auto_rules
    rules = payload.get("auto_rules", [])
    if isinstance(rules, list) and rules:
        try:
            from console.handlers.auto_rule import _load_rules
            _load_rules({"rules": rules})
            summary["rules_count"] = len(rules)
        except Exception as e:
            summary["errors"].append(f"auto_rules: {e}")

    # 恢复串口设置
    settings = payload.get("serial_settings", {})
    if isinstance(settings, dict) and settings:
        try:
            from console.handlers.serial_cmd import _last_settings
            _last_settings.clear()
            _last_settings.update(settings)
            summary["settings_count"] = len(settings)
        except Exception as e:
            summary["errors"].append(f"serial_settings: {e}")

    return summary
