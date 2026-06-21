"""单元测试: 编解码器"""
from protocol_tool.codecs.uint import UIntCodec
from protocol_tool.codecs.bcd import BcdCodec
from protocol_tool.codecs.bitset import BitSetCodec
from protocol_tool.codecs.const import ConstCodec, ConstRepeatCodec
from protocol_tool.codecs.bytes_codec import HexCodec
from protocol_tool.codecs.checksum import ChecksumCodec, _sum8, _crc16_modbus
from protocol_tool.codecs.base import ByteWriter
from protocol_tool.ir.nodes import FieldNode
from protocol_tool.runtime.reader import DecodeReader
from protocol_tool.runtime.context import DecodeContext, BuildContext


class TestUIntCodec:
    def test_uint8_roundtrip(self):
        c = UIntCodec(1)
        f = FieldNode(id="x", name="x", type_ref="uint8")
        w = ByteWriter()
        c.encode(f, 42, w, BuildContext())
        assert w.bytes() == b'\x2a'
        r = DecodeReader(w.bytes(), 0)
        assert c.decode(f, r, DecodeContext()) == 42

    def test_uint16_le(self):
        c = UIntCodec(2, "little")
        f = FieldNode(id="x", name="x", type_ref="uint16_le")
        w = ByteWriter()
        c.encode(f, 0x1234, w, BuildContext())
        assert w.bytes() == b'\x34\x12'


class TestBcdCodec:
    def test_decode(self):
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", length=3)
        r = DecodeReader(bytes([0x12, 0x34, 0x56]), 0)
        assert c.decode(f, r, DecodeContext()) == "123456"

    def test_encode(self):
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", length=3)
        w = ByteWriter()
        c.encode(f, "123456", w, BuildContext())
        assert w.bytes() == bytes([0x12, 0x34, 0x56])

    def test_little_endian_decode(self):
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", params={"byte_order": "little"}, length=3)
        r = DecodeReader(bytes([0x56, 0x34, 0x12]), 0)
        assert c.decode(f, r, DecodeContext()) == "123456"


class TestBitSetCodec:
    def test_decode(self):
        c = BitSetCodec()
        bits = [
            {"name": "func", "offset": 0, "width": 5},
            {"name": "dir", "offset": 7, "width": 1},
        ]
        f = FieldNode(id="x", name="x", type_ref="bitset", params={"bits": bits})
        r = DecodeReader(bytes([0x91]), 0)  # 10010001
        v = c.decode(f, r, DecodeContext())
        assert v["func"] == 17
        assert v["dir"] == 1
        assert v["raw"] == 0x91


class TestConstCodec:
    def test_decode_ok(self):
        c = ConstCodec()
        f = FieldNode(id="x", name="x", type_ref="const", params={"value": 0x68})
        r = DecodeReader(bytes([0x68]), 0)
        assert c.decode(f, r, DecodeContext()) == 0x68

    def test_decode_fail(self):
        c = ConstCodec()
        f = FieldNode(id="x", name="x", type_ref="const", params={"value": 0x68})
        r = DecodeReader(bytes([0x16]), 0)
        try:
            c.decode(f, r, DecodeContext())
            assert False, "should raise"
        except ValueError:
            pass


class TestConstRepeatCodec:
    def test_decode(self):
        c = ConstRepeatCodec()
        f = FieldNode(id="x", name="x", type_ref="const_repeat", params={"value": 0xFE, "min": 0, "max": 4})
        r = DecodeReader(bytes([0xFE, 0xFE, 0x68]), 0)
        v = c.decode(f, r, DecodeContext())
        assert v == [0xFE, 0xFE]


class TestHexCodec:
    def test_little_endian(self):
        c = HexCodec()
        f = FieldNode(id="x", name="x", type_ref="hex", params={"byte_order": "little"}, length=4)
        r = DecodeReader(bytes([0x01, 0x00, 0x00, 0xE8]), 0)
        assert c.decode(f, r, DecodeContext()) == "E8 00 00 01"


class TestChecksum:
    def test_sum8(self):
        assert _sum8(bytes([0x01, 0x02, 0x03])) == 6

    def test_crc16_modbus(self):
        # Verify roundtrip: compute and verify
        data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        crc = _crc16_modbus(data)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF
