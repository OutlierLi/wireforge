"""CLI 参数工具 — 括号数组解析。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from console.arg_utils import (
    coerce_array_value,
    merge_bracket_list_value_tail,
    parse_bracket_list,
)
from console.handlers.build import build_frame_from_args
from console.runtime import parse_command_text


def test_parse_bracket_list_basic():
    assert parse_bracket_list("[000000000001, 000000000002]") == [
        "000000000001",
        "000000000002",
    ]


def test_parse_bracket_list_no_spaces():
    assert parse_bracket_list("[000000000001,000000000002]") == [
        "000000000001",
        "000000000002",
    ]


def test_parse_bracket_list_single():
    assert parse_bracket_list("[000000000001]") == ["000000000001"]


def test_parse_bracket_list_empty():
    assert parse_bracket_list("[]") == []


def test_parse_bracket_list_not_bracket():
    assert parse_bracket_list("000000000001") is None


def test_merge_bracket_list_value_tail():
    parts = [
        "/build",
        "--slave_addrs",
        "[000000000001,",
        "000000000002]",
    ]
    merged, idx = merge_bracket_list_value_tail(parts[2], parts, 2)
    assert merged == "[000000000001, 000000000002]"
    assert idx == 3


def test_parse_command_text_bracket_list_eq():
    cmd, args = parse_command_text(
        "/build --proto=csg --dir=downlink --afn=0x04 --di=E8020402 "
        "--slave_addrs=[000000000001,000000000002]"
    )
    assert cmd == "build"
    assert args["slave_addrs"] == ["000000000001", "000000000002"]


def test_parse_command_text_bracket_list_spaced():
    cmd, args = parse_command_text(
        "/build --proto=csg --dir=downlink --afn=0x04 --di=E8020402 "
        "--slave_addrs [000000000001, 000000000002]"
    )
    assert args["slave_addrs"] == ["000000000001", "000000000002"]


def test_build_add_slave_bracket_list_auto_slave_count():
    import protocol_tool.utils.logger as lg

    lg.log_build = lg.log_decode = lambda *a, **k: None

    cmd, args = parse_command_text(
        "/build --proto=csg --dir=downlink --afn=0x04 --di=E8020402 "
        "--slave_addrs=[000000000001,000000000002]"
    )
    result = build_frame_from_args(args)
    assert result["success"] is True, result.get("error")
    # slave_count=2 推断成功；帧内数据域以 02 开头表示 2 个从节点
    frame = result["data"]["frame"]
    assert " 02 " in f" {frame} "


def test_build_add_slave_bracket_list_count_mismatch():
    import protocol_tool.utils.logger as lg

    lg.log_build = lg.log_decode = lambda *a, **k: None

    result = build_frame_from_args({
        "proto": "csg",
        "dir": "downlink",
        "afn": "0x04",
        "di": "E8020402",
        "slave_count": 3,
        "slave_addrs": "[000000000001,000000000002]",
    })
    assert result["success"] is False
    assert "不一致" in result.get("error", "")


def test_from_frame_set_bracket_list_with_spaces():
    import protocol_tool.utils.logger as lg

    lg.log_build = lg.log_decode = lambda *a, **k: None

    frame = (
        "68 1F 00 40 04 01 02 04 02 E8 03 13 88 03 00 24 01 24 "
        "88 03 00 24 01 25 88 03 00 24 01 A4 16"
    )
    text = (
        f"/build from-frame --from_frame {frame} "
        "--set slave_count=2 "
        "--set slave_addrs=[012400038813, 012400038824]"
    )
    _, args = parse_command_text(text)
    from console.handlers.build import _parse_set_args

    parsed = _parse_set_args(args.get("set"))
    assert parsed["slave_count"] == 2
    assert parsed["slave_addrs"] == ["012400038813", "012400038824"]

    result = build_frame_from_args(args)
    assert result["success"] is True, result.get("error")
