"""Protocol graph projection and build/decode regression tests."""

from pathlib import Path

from console.api import exec_cmd
from protocol_tool.compiler.pipeline import compile_protocol
from protocol_tool.ir.graph import protocol_graph_from_ir

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "protocol_tool" / "protocols" / "registry.yaml"


def _compile(proto: str):
    return compile_protocol(str(REGISTRY), proto)


def _ok(result: dict, msg: str = "") -> None:
    assert result["status"] == "success", f"{msg}: {result}"


def test_dlt645_graph_projection_has_frame_route_and_time_payload():
    graph = protocol_graph_from_ir(_compile("dlt645_2007"))

    assert graph.protocol == "dlt645_2007"
    assert graph.validate() == []
    assert graph.start in graph.nodes

    counts = graph.node_type_counts()
    assert counts["const"] >= 2
    assert counts["patch"] >= 2
    assert counts["virtual"] >= 1
    assert counts["end"] == 1

    assert graph.routes["main"].keys == ("control.func", "control.dir")
    assert graph.routes["main"].fallback == "raw"

    payload = graph.payloads["node:dlt645_2007.broadcast_time_request"]
    assert [field.name for field in payload.fields] == ["datetime"]


def test_csg_graph_projection_has_multi_stage_routes_and_time_payload():
    graph = protocol_graph_from_ir(_compile("csg_2016"))

    assert graph.protocol == "csg_2016"
    assert graph.validate() == []
    assert graph.start in graph.nodes

    counts = graph.node_type_counts()
    assert counts["patch"] >= 2
    assert counts["virtual"] >= 3
    assert counts["end"] == 1

    assert graph.routes["main"].keys == ("control.dir", "control.add")
    assert graph.routes["afn_router"].keys == ("afn",)
    assert graph.routes["afn06_di_router"].keys == ("di", "control.dir", "control.add")

    request_payload = graph.payloads["node:csg_2016.csg_2016.afn06_request_time"]
    assert [field.name for field in request_payload.fields] == []
    assert request_payload.router_id == "afn06_di_router"
    assert request_payload.route_key == '["E8060601",0,0]'

    payload = graph.payloads["node:csg_2016.csg_2016.afn06_request_time_resp"]
    assert [field.name for field in payload.fields] == ["datetime"]
    assert payload.router_id == "afn06_di_router"
    assert payload.route_key == '["E8060601",1,0]'


def test_dlt645_build_and_decode_broadcast_time_request():
    build_result = exec_cmd("build", {
        "proto": "dlt645",
        "func": "0x08",
        "dir": "downlink",
        "datetime.year": "26",
        "datetime.month": "06",
        "datetime.day": "26",
        "datetime.hour": "21",
        "datetime.minute": "49",
        "datetime.second": "06",
    })
    _ok(build_result, "build 645 broadcast time")

    frame = build_result["data"]["frame"]
    decode_result = exec_cmd("decode", {"proto": "dlt645", "hex": frame})
    _ok(decode_result, "decode 645 broadcast time")

    data = decode_result["data"]
    assert "broadcast_time_request" in data["path"]
    decoded_time = data["values"]["data"]["datetime"]
    assert decoded_time == {
        "year": "26",
        "month": "06",
        "day": "26",
        "hour": "21",
        "minute": "49",
        "second": "06",
    }


def test_csg_build_and_decode_request_time_response():
    build_result = exec_cmd("build", {
        "proto": "csg",
        "afn": "0x06",
        "di": "E8060601",
        "dir": "uplink",
        "datetime.year": "26",
        "datetime.month": "06",
        "datetime.day": "26",
        "datetime.hour": "21",
        "datetime.minute": "49",
        "datetime.second": "06",
    })
    _ok(build_result, "build CSG request time response")

    frame = build_result["data"]["frame"]
    decode_result = exec_cmd("decode", {"proto": "csg", "hex": frame})
    _ok(decode_result, "decode CSG request time response")

    data = decode_result["data"]
    assert "afn06_request_time_resp" in data["path"]
    user_data = data["values"]["user_data"]
    assert user_data["afn"] == 6
    assert user_data["di"] == "E8 06 06 01"
    decoded_time = user_data["data_content"]["di_payload"]["datetime"]
    assert decoded_time == {
        "second": "06",
        "minute": "49",
        "hour": "21",
        "day": "26",
        "month": "06",
        "year": "26",
    }
