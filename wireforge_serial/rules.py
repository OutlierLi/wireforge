"""规则引擎 — 串口自动应答。

支持三种匹配模式:
  - hex: 精确匹配 / 包含匹配 / 正则匹配
  - csg:  按 AFN + DI 匹配 CSG 帧
  - dlt645: 按 func + address + di 匹配 DLT645 帧

规则从 YAML 文件加载，格式:
  rules:
    - name: dlt645-read-address
      enabled: true
      match:
        dlt645: { func: "13" }
      reply:
        dlt645: { func: "93", address: "000000000001", payload: { raw: "..." } }
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleAction:
    name: str = ""
    action_type: str = "reply"  # reply | send | wait | log
    payload: bytes | None = None
    delay_ms: int = 0
    repeat: int = 1
    interval_ms: int = 0


@dataclass
class RuleMatchResult:
    name: str = ""
    actions: list[RuleAction] = field(default_factory=list)

    @property
    def reply(self) -> bytes | None:
        return self.actions[0].payload if self.actions else None

    @property
    def delay_ms(self) -> int:
        return self.actions[0].delay_ms if self.actions else 0


class RuleEngine:
    """串口规则引擎。"""

    def __init__(self, rules: list[dict], schema_root: str | None = None):
        self._rules = [r for r in rules if r.get("enabled", True)]
        self._schema_root = schema_root
        self._csg_parser = None
        self._dlt645_parser = None

    @classmethod
    def from_file(cls, path: str, schema_root: str | None = None) -> RuleEngine:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(data.get("rules", []), schema_root)

    def match(self, data: bytes) -> RuleMatchResult | None:
        """匹配接收到的字节流，返回第一条命中规则。"""
        hex_str = data.hex().upper()
        for rule in self._rules:
            matcher = rule.get("match", {})
            if not matcher:
                continue
            if self._try_match(hex_str, data, matcher):
                actions = self._build_actions(rule)
                return RuleMatchResult(name=rule.get("name", ""), actions=actions)
        return None

    def _try_match(self, hex_str: str, data: bytes, matcher: dict) -> bool:
        # hex matcher
        hm = matcher.get("hex", matcher.get("hex_raw"))
        if hm:
            if not self._match_hex(hex_str, hm):
                return False

        # CSG matcher
        cm = matcher.get("csg")
        if cm:
            if not self._match_csg(data, cm):
                return False

        # DLT645 matcher
        dm = matcher.get("dlt645")
        if dm:
            if not self._match_dlt645(data, dm):
                return False

        return True

    def _match_hex(self, hex_str: str, spec: dict | str) -> bool:
        if isinstance(spec, str):
            return spec.upper() in hex_str
        if "exact" in spec:
            return spec["exact"].upper().replace(" ", "") == hex_str
        if "contains" in spec:
            return spec["contains"].upper().replace(" ", "") in hex_str
        if "regex" in spec:
            return bool(re.search(spec["regex"], hex_str, re.IGNORECASE))
        return False

    def _match_csg(self, data: bytes, spec: dict) -> bool:
        try:
            parsed = self._get_csg_parser().parse(data) if self._get_csg_parser() else {}
        except Exception:
            return False
        for key, val in spec.items():
            pv = parsed.get(key)
            if pv is None:
                return False
            if isinstance(val, str):
                if str(pv).upper().replace(" ", "") != val.upper().replace(" ", ""):
                    return False
            elif pv != val:
                return False
        return True

    def _match_dlt645(self, data: bytes, spec: dict) -> bool:
        try:
            parsed = self._get_dlt645_parser().parse(data) if self._get_dlt645_parser() else {}
        except Exception:
            return False
        for key, val in spec.items():
            pv = parsed.get(key)
            if pv is None:
                return False
            if isinstance(val, str):
                if str(pv).upper().replace(" ", "") != val.upper().replace(" ", ""):
                    return False
            elif pv != val:
                return False
        return True

    def _get_csg_parser(self):
        if self._csg_parser is None:
            try:
                from protocol_tool.parser import ProtocolParser
                self._csg_parser = ProtocolParser("csg_2016", schema_root=self._schema_root)
            except Exception:
                pass
        return self._csg_parser

    def _get_dlt645_parser(self):
        if self._dlt645_parser is None:
            try:
                from protocol_tool.parser import ProtocolParser
                self._dlt645_parser = ProtocolParser("dlt645_2007", schema_root=self._schema_root)
            except Exception:
                pass
        return self._dlt645_parser

    def _build_actions(self, rule: dict) -> list[RuleAction]:
        actions = rule.get("actions", [])
        if not actions:
            reply = rule.get("reply")
            if reply:
                actions = [{"type": "reply", **reply}]
        result = []
        for a in actions:
            payload = None
            raw = a.get("frame") or a.get("payload", {}).get("raw")
            if raw:
                payload = bytes.fromhex(raw.replace(" ", ""))
            result.append(RuleAction(
                name=rule.get("name", ""),
                action_type=a.get("type", "reply"),
                payload=payload,
                delay_ms=a.get("delay_ms", 0),
                repeat=a.get("repeat", 1),
                interval_ms=a.get("interval_ms", 0),
            ))
        return result


def apply_reply_delay(match: RuleMatchResult):
    if match.delay_ms > 0:
        time.sleep(match.delay_ms / 1000.0)
