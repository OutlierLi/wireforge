"""Unit tests for source fidelity checking."""

from __future__ import annotations

from protocol_extend.fidelity_checker import accept_allowed, check_fidelity, fidelity_preview
from protocol_extend.fields import field_to_yaml
from protocol_extend.schema import ExtensionSpec
from protocol_extend.source_snapshot import build_source_snapshot_from_draft
from extractor.extension_draft import ExtensionDraft


def _spec(**kwargs) -> ExtensionSpec:
    defaults = dict(afn=3, di="E8030304", description="查询通信延时时长", dir=0, add=False)
    defaults.update(kwargs)
    return ExtensionSpec(**defaults)


def test_fidelity_high_when_yaml_matches_snapshot():
    draft = ExtensionDraft(
        afn=3,
        di="E8030304",
        description="查询通信延时时长",
        dir=0,
        add=False,
        fields=[
            {
                "name": "dest_addr",
                "desc": "通信目的地址",
                "bytes": 6,
                "evidence": ["通信目的地址"],
            },
            {
                "name": "payload_length",
                "desc": "报文长度",
                "bytes": 1,
                "evidence": ["报文长度"],
            },
        ],
    )
    snapshot = build_source_snapshot_from_draft(draft)
    spec = draft.to_spec()
    report = check_fidelity(snapshot, spec)
    assert report["confidence"] == "high"
    assert accept_allowed(report)
    assert not fidelity_preview(report)["failed_checks"]


def test_fidelity_low_on_description_dir_field_mismatch():
    snapshot = {
        "source": "docx",
        "title": "查询通信延时时长",
        "description": "查询通信延时时长",
        "di": "E8030304",
        "afn": 3,
        "dir_hint": 0,
        "field_rows": [
            {"name": "dest_addr", "desc": "通信目的地址", "bytes": 6, "evidence": ["通信目的地址"], "raw_row": []},
            {"name": "payload_length", "desc": "报文长度", "bytes": 1, "evidence": ["报文长度"], "raw_row": []},
        ],
        "fields": [],
    }
    spec = _spec(
        description="查询从节点数量",
        dir=1,
        fields=[{"name": "dest_addr", "desc": "通信目的地址", "type": "bcd", "length": 6}],
    )
    report = check_fidelity(snapshot, spec)
    assert report["confidence"] in ("medium", "low")
    assert not accept_allowed(report)
    failed_ids = {c["id"] for c in report["checks"] if not c.get("ok")}
    assert "description_match" in failed_ids
    assert "dir_match" in failed_ids
    assert "field_count" in failed_ids


def test_fidelity_flags_missing_enum_for_switch_field():
    snapshot = {
        "source": "docx",
        "title": "查询本地通信模块运行模式信息",
        "description": "查询本地通信模块运行模式信息",
        "di": "E8000302",
        "afn": 3,
        "dir_hint": 0,
        "field_rows": [
            {
                "name": "local_mode_word",
                "desc": "0：路由模式 1：中继模式",
                "bytes": 1,
                "evidence": ["0：路由模式", "1：中继模式"],
                "raw_row": ["local_mode_word", "1字节", "0：路由模式 1：中继模式"],
            },
        ],
        "fields": [],
    }
    spec = ExtensionSpec(
        afn=3,
        di="E8000302",
        description="查询本地通信模块运行模式信息",
        dir=0,
        add=False,
        fields=[{"name": "local_mode_word", "desc": "本地通信模式字", "type": "uint8"}],
    )
    report = check_fidelity(snapshot, spec)
    types_check = next(c for c in report["checks"] if c["id"] == "field_types")
    assert types_check["ok"] is False
    assert report["confidence"] != "high"
    assert not accept_allowed(report)


def test_fidelity_force_allows_medium():
    report = {"confidence": "medium", "score": 65, "summary": "test", "checks": []}
    assert not accept_allowed(report)
    assert accept_allowed(report, force=True)
