"""CSG protocol_map 示例完整性测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from console.handlers.find import handle as find_handle

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "compiled" / "protocol_map.json"


@pytest.fixture(scope="module")
def csg_entries():
    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    return data["protocols"]["csg_2016"]["entries"]


def test_all_csg_entries_have_build_and_frame_examples(csg_entries):
    missing = []
    for entry in csg_entries:
        if not entry.get("build_example") or not entry.get("frame_example"):
            missing.append(entry.get("entry_id", entry.get("name")))
    assert not missing, f"missing examples: {missing}"


def test_csg_frame_examples_are_non_empty_hex(csg_entries):
    for entry in csg_entries:
        frame = entry.get("frame_example", "")
        clean = frame.replace(" ", "")
        assert clean, entry["entry_id"]
        assert all(c in "0123456789ABCDEFabcdef" for c in clean), entry["entry_id"]
        assert clean.endswith("16"), entry["entry_id"]


def test_find_returns_examples_for_csg_init_archive():
    result = find_handle({"proto": "csg", "q": "初始化档案"})
    assert result["success"] is True
    assert result["data"]["count"] >= 1
    hit = next(
        item for item in result["data"]["results"]
        if "init_archive" in item.get("name", "")
    )
    assert hit.get("build_example", "").startswith("/build --proto=csg")
    assert hit.get("frame_example")
    assert isinstance(hit.get("build_args"), dict)


def test_find_returns_route_hints_when_proto_partial():
    result = find_handle({"proto": "csg", "afn": "0x01"})
    assert result["success"] is True
    hints = result["data"].get("route_hints")
    assert hints is not None
    assert "dir" in hints["pending_keys"] or "di" in hints["pending_keys"]
    assert hints.get("hint")
    assert hints.get("suggestions")


def test_find_by_di_includes_frame_example():
    result = find_handle({"proto": "csg", "di": "E8060601", "dir": "uplink"})
    assert result["success"] is True
    assert result["data"]["count"] == 1
    item = result["data"]["results"][0]
    assert item["route_params"]["di"] == "E8060601"
    assert "build_example" in item
    assert "frame_example" in item
