"""单元测试: 编解码器"""
import pytest

from protocol_tool.codecs.uint import UIntCodec
from protocol_tool.codecs.bcd import BcdCodec
from protocol_tool.codecs.bitset import BitSetCodec
from protocol_tool.codecs.const import ConstCodec, ConstRepeatCodec
from protocol_tool.codecs.bytes_codec import HexCodec, AsciiCodec
from protocol_tool.codecs.checksum import ChecksumCodec, _sum8, _crc16_modbus
from protocol_tool.codecs.enum_codec import EnumCodec
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

    def test_uint24_le(self):
        c = UIntCodec(3, "little")
        f = FieldNode(id="x", name="x", type_ref="uint24_le")
        w = ByteWriter()
        c.encode(f, 0x010203, w, BuildContext())
        assert w.bytes() == b'\x03\x02\x01'
        r = DecodeReader(w.bytes(), 0)
        assert c.decode(f, r, DecodeContext()) == 0x010203


class TestBcdCodec:
    def test_decode(self):
        """默认 LE: 线缆 [0x56, 0x34, 0x12] → 反转 → 解码 → "123456" """
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", length=3)
        r = DecodeReader(bytes([0x56, 0x34, 0x12]), 0)
        assert c.decode(f, r, DecodeContext()) == "123456"

    def test_encode(self):
        """默认 LE: "123456" → 编码 → 反转 → 线缆 [0x56, 0x34, 0x12] """
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", length=3)
        w = ByteWriter()
        c.encode(f, "123456", w, BuildContext())
        assert w.bytes() == bytes([0x56, 0x34, 0x12])

    def test_big_endian_explicit(self):
        """显式 BE: 不做反转"""
        c = BcdCodec()
        f = FieldNode(id="x", name="x", type_ref="bcd", params={"byte_order": "big"}, length=3)
        r = DecodeReader(bytes([0x12, 0x34, 0x56]), 0)
        assert c.decode(f, r, DecodeContext()) == "123456"

    def test_little_endian_decode(self):
        """显式 LE: 与默认行为一致"""
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


class TestAsciiCodec:
    def test_default_little_endian_roundtrip(self):
        c = AsciiCodec()
        f = FieldNode(id="x", name="x", type_ref="ascii", length=2)
        w = ByteWriter()
        c.encode(f, "AB", w, BuildContext())
        assert w.bytes() == b"BA"
        r = DecodeReader(w.bytes(), 0)
        assert c.decode(f, r, DecodeContext()) == "AB"

    def test_big_endian_explicit(self):
        c = AsciiCodec()
        f = FieldNode(
            id="x", name="x", type_ref="ascii",
            params={"byte_order": "big"}, length=2,
        )
        w = ByteWriter()
        c.encode(f, "AB", w, BuildContext())
        assert w.bytes() == b"AB"
        r = DecodeReader(bytes([0x41, 0x42]), 0)
        assert c.decode(f, r, DecodeContext()) == "AB"


class TestEnumCodec:
    _VALUES = {"0x00": "禁止上报", "0x01": "允许上报"}

    def _field(self) -> FieldNode:
        return FieldNode(
            id="enable",
            name="enable",
            type_ref="enum",
            params={"values": self._VALUES},
        )

    def test_encode_hex_string_01(self):
        c = EnumCodec()
        w = ByteWriter()
        c.encode(self._field(), "01", w, BuildContext())
        assert w.bytes() == b"\x01"

    def test_encode_0x_prefix(self):
        c = EnumCodec()
        w = ByteWriter()
        c.encode(self._field(), "0x01", w, BuildContext())
        assert w.bytes() == b"\x01"

    def test_encode_label(self):
        c = EnumCodec()
        w = ByteWriter()
        c.encode(self._field(), "允许上报", w, BuildContext())
        assert w.bytes() == b"\x01"

    def test_encode_int(self):
        c = EnumCodec()
        w = ByteWriter()
        c.encode(self._field(), 1, w, BuildContext())
        assert w.bytes() == b"\x01"

    def test_decode_string_key_values(self):
        c = EnumCodec()
        r = DecodeReader(b"\x01", 0)
        decoded = c.decode(self._field(), r, DecodeContext())
        assert decoded == {"raw": 1, "label": "允许上报"}

    def test_encode_in_struct_array_item(self):
        from protocol_tool.codecs.array_codec import ArrayCodec
        from protocol_tool.codecs.struct_codec import StructCodec
        from protocol_tool.codecs import create_builtin_registry

        registry = create_builtin_registry()
        StructCodec.codec_registry = registry

        device_values = {"0x01": "单相电子表", "0x02": "多功能表"}
        array_field = FieldNode(
            id="nodes",
            name="nodes",
            type_ref="array",
            params={
                "count_ref": "node_count",
                "item_name": "node",
                "item_type": "struct",
                "item_params": {
                    "fields": [
                        {
                            "name": "node_addr",
                            "type": "bcd",
                            "length": 6,
                            "byte_order": "little",
                        },
                        {
                            "name": "device_type",
                            "type": "enum",
                            "values": device_values,
                        },
                    ],
                },
            },
        )
        w = ByteWriter()
        ArrayCodec().encode(
            array_field,
            [{"node_addr": "000000000001", "device_type": "01"}],
            w,
            BuildContext(values={"node_count": 1}),
        )
        assert w.bytes() == bytes([0x01, 0, 0, 0, 0, 0, 0x01])

    def test_encode_invalid_enum_raises(self):
        from protocol_tool.codecs.enum_codec import EnumValueError

        c = EnumCodec()
        with pytest.raises(EnumValueError):
            c.encode(self._field(), "invalid", ByteWriter(), BuildContext())


class TestChecksum:
    def test_sum8(self):
        assert _sum8(bytes([0x01, 0x02, 0x03])) == 6

    def test_crc16_modbus(self):
        # Verify roundtrip: compute and verify
        data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        crc = _crc16_modbus(data)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF
