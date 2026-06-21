"""单元测试: 运行时引擎"""
from protocol_tool.runtime.reader import DecodeReader, BufferOverrunError
from protocol_tool.runtime.router import Router, RouteError
from protocol_tool.runtime.context import DecodeContext
from protocol_tool.ir.nodes import RouterNode


class TestDecodeReader:
    def test_basic_read(self):
        r = DecodeReader(bytes([0x68, 0x11, 0x04, 0x16]))
        assert r.read(2) == bytes([0x68, 0x11])
        assert r.remaining() == 2
        assert r.read(2) == bytes([0x04, 0x16])
        assert r.exhausted()

    def test_overrun(self):
        r = DecodeReader(bytes([0x68]), 0, 1)
        try:
            r.read(2)
            assert False, "should raise"
        except BufferOverrunError:
            pass

    def test_fork(self):
        r = DecodeReader(bytes([0x01, 0x02, 0x03]), 0)
        r.read(1)  # advance to 1
        f = r.fork()
        assert f.tell() == 1
        assert f.read(2) == bytes([0x02, 0x03])
        assert r.tell() == 1  # parent unchanged


class TestRouter:
    def test_resolve_hit(self):
        node = RouterNode(
            id="test", key_paths=("func", "dir"),
            route_table={"[17,0]": "leaf_a", "[17,1]": "leaf_b"},
        )
        router = Router(node)
        ctx = DecodeContext()
        ctx.set("func", 17)
        ctx.set("dir", 1)
        assert router.resolve(ctx) == "leaf_b"

    def test_resolve_miss_error(self):
        node = RouterNode(
            id="test", key_paths=("func",),
            route_table={"[0]": "leaf"}, fallback_policy="error",
        )
        router = Router(node)
        ctx = DecodeContext()
        ctx.set("func", 99)
        try:
            router.resolve(ctx)
            assert False
        except RouteError:
            pass

    def test_resolve_miss_raw(self):
        node = RouterNode(
            id="test", key_paths=("func",),
            route_table={}, fallback_policy="raw",
        )
        router = Router(node)
        ctx = DecodeContext()
        ctx.set("func", 99)
        assert router.resolve(ctx) == "raw_remaining"
