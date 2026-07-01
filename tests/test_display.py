"""CLI 紧凑显示逻辑测试。"""

from io import StringIO

from console.api import exec_cmd, exec_text
from console.display import format_decode_fields, render_response, try_compact_display


def _ok(r):
    assert r["status"] == "success", r


def test_build_success_compact_frame_only():
    r = exec_cmd("build", {
        "proto": "csg",
        "afn": "0x00",
        "di": "E8010001",
        "dir": "downlink",
        "wait_time": "0",
    })
    _ok(r)
    lines = try_compact_display("/build --proto csg --afn 0x00 --di E8010001 --dir downlink --wait_time 0", r)
    assert lines is not None
    assert len(lines) == 1
    assert lines[0].startswith("[build]:")
    assert "68" in lines[0]


def test_build_resolve_not_compact():
    r = exec_cmd("build", {
        "proto": "csg",
        "afn": "0x00",
        "di": "E8010001",
        "dir": "downlink",
        "resolve": True,
    })
    _ok(r)
    assert try_compact_display("/build --proto csg --resolve", r) is None


def test_serial_send_success_compact():
    exec_cmd("serial", {"sub": "connect", "port": "mock://loop"})
    r = exec_cmd("serial", {"sub": "send", "hex": "68 16", "to": "default"})
    _ok(r)
    lines = try_compact_display("/serial send --hex 68 16", r)
    assert lines == ["[default] TX: 68 16"]


def test_serial_send_failure_full_render():
    exec_cmd("serial", {"sub": "close"})
    r = exec_cmd("serial", {"sub": "send", "hex": "68 16"})
    out = StringIO()
    render_response("/serial send --hex 68 16", r, out)
    text = out.getvalue()
    assert "success" not in text
    assert "not connected" in text.lower() or "execution_error" in text or "error" in text.lower()


def test_decode_success_compact_fields():
    r = exec_cmd("decode", {
        "proto": "csg",
        "hex": "68 0C 00 40 03 01 01 03 00 E8 30 16",
    })
    _ok(r)
    assert r["data"].get("fields")
    lines = try_compact_display("/decode --proto csg --hex 68 0C 00 40 03 01 01 03 00 E8 30 16", r)
    assert lines is not None
    assert lines[0].startswith("68")
    assert any("@03" in line and "control" in line for line in lines)


def test_decode_failure_full_render():
    r = exec_cmd("decode", {"proto": "csg", "hex": "DE AD BE EF"})
    out = StringIO()
    render_response("/decode --proto csg --hex DE AD BE EF", r, out)
    text = out.getvalue()
    assert "success" not in text.splitlines()[0:1]


def test_build_failure_has_tag():
    r = exec_cmd("build", {"proto": "csg", "afn": "0x99", "di": "FFFFFFFF", "dir": "downlink"})
    out = StringIO()
    render_response("/build --proto csg --afn 0x99 --di FFFFFFFF --dir downlink", r, out)
    assert out.getvalue().startswith("[build]:")


def test_build_resolve_success_has_tag():
    r = exec_cmd("build", {
        "proto": "csg",
        "afn": "0x00",
        "di": "E8010001",
        "dir": "downlink",
        "resolve": True,
    })
    _ok(r)
    out = StringIO()
    render_response("/build --proto csg --resolve", r, out)
    assert out.getvalue().startswith("[build]: success\n")


def test_format_decode_fields_from_data():
    data = {
        "frame": "68 16",
        "fields": [
            {"offset": 0, "path": "start", "wire_hex": "68", "value": 104},
            {"offset": 1, "path": "end", "wire_hex": "16", "value": 22},
        ],
    }
    lines = format_decode_fields(data)
    assert lines[0] == "68 16"
    assert "@00" in lines[1]
    assert "start" in lines[1]
