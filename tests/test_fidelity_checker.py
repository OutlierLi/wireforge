"""Unit tests for source fidelity checking."""

from __future__ import annotations

from protocol_extend.fidelity_checker import accept_allowed, check_fidelity, fidelity_preview
from protocol_extend.fields import field_to_yaml
from protocol_extend.schema import ExtensionSpec
from protocol_extend.source_snapshot import build_source_snapshot_from_draft
from extractor.extension_draft import ExtensionDraft


def _spec(**kwargs) -> ExtensionSpec:
    defaults = dict(afn=5, di="E80505A0", description="上报未识别节点信息", dir=1, add=False)
    defaults.update(kwargs)
    return ExtensionSpec(**defaults)


def test_fidelity_high_when_yaml_matches_snapshot():
    draft = ExtensionDraft(
        afn=5,
        di="E80505A0",
        description="上报未识别节点信息",
        dir=1,
        add=False,
        fields=[
            {
                "name": "node_count",
                "desc": "节点数量",
                "bytes": 1,
                "evidence": ["节点数量"],
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
        "title": "上报未识别节点",
        "description": "上报未识别节点",
        "di": "E80505A0",
        "afn": 5,
        "dir_hint": 1,
        "field_rows": [
            {"name": "node_count", "desc": "节点数量", "bytes": 1, "evidence": ["节点数量"], "raw_row": []},
            {"name": "nodes", "desc": "节点列表", "bytes": None, "evidence": [], "raw_row": []},
        ],
        "fields": [],
    }
    spec = _spec(
        description="1. 查询黑名单节点信息",
        dir=0,
        fields=[{"name": "node_count", "desc": "节点数量", "type": "uint8"}],
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
        "title": "设置上电即上线功能开关",
        "description": "设置上电即上线功能开关",
        "di": "E80204A0",
        "afn": 2,
        "dir_hint": 0,
        "field_rows": [
            {
                "name": "power_on_switch",
                "desc": "0：关闭 1：打开",
                "bytes": 1,
                "evidence": ["0：关闭", "1：打开"],
                "raw_row": ["power_on_switch", "1字节", "0：关闭 1：打开"],
            },
        ],
        "fields": [],
    }
    spec = ExtensionSpec(
        afn=2,
        di="E80204A0",
        description="设置上电即上线功能开关",
        dir=0,
        add=False,
        fields=[{"name": "power_on_switch", "desc": "上电即上线功能开关", "type": "uint8"}],
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
