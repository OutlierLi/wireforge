"""批量配置加载器 — 从 YAML 读取批量发送配置。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BatchMessage:
    name: str = ""
    frame: str = ""
    wait_response: bool = True
    timeout: float = 1.0
    retries: int = 0
    delay_ms: int = 0


@dataclass
class BatchConfig:
    defaults: dict = field(default_factory=dict)
    messages: list[BatchMessage] = field(default_factory=list)


def load_batch_config(path: str) -> BatchConfig:
    """从 YAML 文件加载批量配置。"""
    import yaml
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {})
    messages = []
    for item in data.get("messages", []):
        messages.append(BatchMessage(
            name=item.get("name", ""),
            frame=item.get("frame", ""),
            wait_response=item.get("wait_response", defaults.get("wait_response", True)),
            timeout=item.get("timeout", defaults.get("timeout", 1.0)),
            retries=item.get("retries", defaults.get("retries", 0)),
            delay_ms=item.get("delay_ms", 0),
        ))
    return BatchConfig(defaults=defaults, messages=messages)
