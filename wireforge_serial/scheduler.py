"""规则动作调度器 — 按序执行 reply/wait/log 动作。"""

from __future__ import annotations

import time
from typing import Protocol

from wireforge_serial.rules import RuleMatchResult


class ActionTransport(Protocol):
    def write(self, data: bytes) -> int: ...


class RuleActionScheduler:
    """执行规则匹配后的动作序列。"""

    def run(self, transport: ActionTransport, match: RuleMatchResult) -> list[str]:
        events = []
        for action in match.actions:
            if action.delay_ms:
                time.sleep(action.delay_ms / 1000.0)
            for i in range(action.repeat):
                if action.action_type in ("reply", "send", "report"):
                    if action.payload:
                        transport.write(action.payload)
                        events.append(f"REPLY[{i+1}/{action.repeat}]: {action.payload.hex(' ').upper()}")
                elif action.action_type == "wait":
                    events.append(f"WAIT: {action.name}")
                elif action.action_type == "log":
                    events.append(f"LOG: {action.name}")
                if action.interval_ms and i < action.repeat - 1:
                    time.sleep(action.interval_ms / 1000.0)
        return events
