from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class LabError(ValueError):
    pass


@dataclass
class ChannelRef:
    target: str
    channel: str
    conn: str
    port: str = ""
    role: str = ""
    protocol: str = ""
    required: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "target": self.target,
            "channel": self.channel,
            "conn": self.conn,
            "port": self.port,
            "role": self.role,
            "protocol": self.protocol,
            "required": self.required,
        }
        extra = {k: v for k, v in self.config.items() if k not in out and k != "conn"}
        if extra:
            out["config"] = extra
        return out


class LabContext:
    """In-process Lab Service boundary for target/channel aware TestPlans.

    v1 keeps the existing serial runtime, but centralizes the translation from
    ``target + channel`` to the current serial connection name.
    """

    def __init__(self, targets: dict[str, dict[str, Any]]):
        self.targets = targets
        self.used_channels: dict[str, ChannelRef] = {}

    @classmethod
    def from_plan(cls, plan: dict[str, Any]) -> "LabContext":
        profiles = _profile_map(plan)
        targets: dict[str, dict[str, Any]] = {}

        if isinstance(plan.get("targets"), dict):
            for alias, spec in plan["targets"].items():
                targets[str(alias)] = _resolve_target_spec(str(alias), spec, profiles)
        elif isinstance(plan.get("channels"), dict):
            alias = str(plan.get("target_id") or plan.get("name") or "target")
            targets[alias] = _resolve_target_spec(alias, plan, profiles)

        return cls(targets)

    def resolve(self, target: Any, channel: Any) -> ChannelRef:
        target_name = str(target or "").strip()
        channel_name = str(channel or "").strip()
        if not target_name:
            raise LabError("target is required when channel is specified")
        if not channel_name:
            raise LabError(f"target {target_name} requires channel")
        target_spec = self.targets.get(target_name)
        if target_spec is None:
            raise LabError(f"target {target_name} not found")
        channels = target_spec.get("channels")
        if not isinstance(channels, dict):
            raise LabError(f"target {target_name} has no channels")
        raw_channel = channels.get(channel_name)
        if not isinstance(raw_channel, dict):
            raise LabError(f"target {target_name} has no channel {channel_name}")

        conn = str(raw_channel.get("conn") or f"{target_name}_{channel_name}")
        ref = ChannelRef(
            target=target_name,
            channel=channel_name,
            conn=conn,
            port=str(raw_channel.get("port") or ""),
            role=str(raw_channel.get("role") or ""),
            protocol=str(raw_channel.get("protocol") or raw_channel.get("proto") or ""),
            required=bool(raw_channel.get("required", False)),
            config=dict(raw_channel),
        )
        self.used_channels[f"{target_name}.{channel_name}"] = ref
        return ref

    def translate_args(self, action: str, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        out = deepcopy(args)
        target = out.pop("target", None)
        channel = out.pop("channel", None)
        scope = out.pop("scope", None)

        if isinstance(scope, dict):
            target = scope.get("target", target)
            channel = scope.get("channel", channel)

        if target in (None, "") and channel in (None, ""):
            return out, None

        ref = self.resolve(target, channel)
        lab_meta = ref.to_dict()
        lab_meta["source"] = f"serial:{ref.conn}"

        if action in {"serial.connect", "serial.open", "serial.set"}:
            out.setdefault("name", ref.conn)
            out.setdefault("port", ref.port)
            for key in ("baudrate", "bytesize", "parity", "stopbits", "timeout", "display"):
                if key in ref.config:
                    out.setdefault(key, ref.config[key])
        elif action in {"serial.disconnect", "serial.close"}:
            out.setdefault("name", ref.conn)
        elif action in {"send", "serial.send", "wait-frame", "wait_frame", "request"}:
            out.setdefault("to", ref.conn)
            if ref.protocol:
                out.setdefault("proto", ref.protocol)
        elif action.startswith("auto_rule."):
            out.setdefault("source", f"serial:{ref.conn}")
            if ref.protocol:
                out.setdefault("proto", ref.protocol)
        else:
            out.setdefault("to", ref.conn)

        return out, lab_meta

    def lease_summary(self) -> dict[str, Any]:
        grouped: dict[str, dict[str, Any]] = {}
        for ref in self.used_channels.values():
            item = grouped.setdefault(ref.target, {
                "target_id": self.targets.get(ref.target, {}).get("target_id") or ref.target,
                "channels": [],
            })
            if ref.channel not in item["channels"]:
                item["channels"].append(ref.channel)
        return {"targets": grouped}

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": self.targets,
            "lease": self.lease_summary(),
        }


def _profile_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = plan.get("target_profiles") or plan.get("profiles") or {}
    return deepcopy(raw) if isinstance(raw, dict) else {}


def _resolve_target_spec(
    alias: str,
    spec: Any,
    profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(spec, str):
        spec = {"profile": spec}
    if not isinstance(spec, dict):
        raise LabError(f"target {alias} must be an object")

    profile_name = str(spec.get("profile") or "")
    base = deepcopy(profiles.get(profile_name) or {})
    merged = {**base, **deepcopy(spec)}
    merged.setdefault("target_id", merged.get("id") or profile_name or alias)
    if "channels" not in merged and "channel" in merged:
        merged["channels"] = {"data": merged.pop("channel")}
    if "channels" in merged and not isinstance(merged["channels"], dict):
        raise LabError(f"target {alias}.channels must be an object")
    return merged
