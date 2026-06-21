"""单元测试: 编译流程"""
import tempfile
from pathlib import Path
from protocol_tool.compiler.loader import CompilationUnit
from protocol_tool.compiler.resolver import Resolver
from protocol_tool.compiler.router_builder import RouterBuilder
from protocol_tool.compiler.validator import Validator
from protocol_tool.ir.nodes import ProtocolIR, FrameNode, FieldNode, RouterNode, LeafNode


class TestResolver:
    def test_resolve_builtin(self):
        unit = CompilationUnit("test", Path("/tmp"))
        r = Resolver(unit)
        assert r.resolve_field_type("uint8") == {"type": "uint8"}
        assert r.resolve_field_type("bcd") == {"type": "bcd"}

    def test_resolve_custom_type(self):
        unit = CompilationUnit("test", Path("/tmp"))
        unit.types_data["energy_4"] = {"type": "bcd_numeric", "length": 4}
        r = Resolver(unit)
        result = r.resolve_field_type("energy_4")
        assert result["type"] == "bcd_numeric"
        assert result["length"] == 4


class TestRouterBuilder:
    def test_normalize_hex_key(self):
        assert RouterBuilder._normalize_route_key([0x11]) == "[17]"
        assert RouterBuilder._normalize_route_key(["00010000"]) == "00010000"
        assert RouterBuilder._normalize_route_key([0x11, 0]) == "[17,0]"

    def test_duplicate_detection(self):
        from protocol_tool.compiler.message_compiler import MessageBinding
        unit = CompilationUnit("test", Path("/tmp"))
        unit.protocol_data = {"routers": {"main": {"keys": ["func"], "fallback": "error"}}}
        b1 = MessageBinding("msg_a", "main", [0x11], "", "leaf_a")
        b2 = MessageBinding("msg_b", "main", [0x11], "", "leaf_b")
        builder = RouterBuilder(unit)
        try:
            builder.build([b1, b2], [])
            assert False, "should detect duplicate"
        except ValueError:
            pass


class TestValidator:
    def test_valid_ir(self):
        ir = ProtocolIR(
            protocol="test",
            frame=FrameNode(id="f", fields=(
                FieldNode(id="f.a", name="a", type_ref="uint8"),
                FieldNode(id="f.b", name="b", type_ref="routed_payload",
                          params={"router": "main"}),
            )),
            routers={"main": RouterNode(id="main", key_paths=("a",), route_table={"[0]": "leaf"})},
            leaves={"leaf": LeafNode(id="leaf", name="leaf")},
        )
        v = Validator()
        issues = v.validate(ir)
        assert issues == []
