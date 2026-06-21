#!/usr/bin/env python3
"""
全量报文 Build → Decode 往返测试

对所有 DLT645-2007 和 CSG-2016 可识别报文执行 build → decode 往返验证。
日志输出到 tests/roundtrip_test/logs/ 目录下。

用法: python3 tests/roundtrip_test/run_all.py
"""

import sys
import json
import random
import datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from protocol_tool.ir.nodes import ProtocolIR
from protocol_tool.codecs import create_builtin_registry
from protocol_tool.runtime.engine import DecodeEngine, BuildEngine

# ── 配置 ──────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent / "logs"
COMPILED_DIR = _project_root / "compiled"

NOW = datetime.datetime.now()
CURRENT_TIME_6 = NOW.strftime("%y%m%d%H%M%S")
CURRENT_TIME_5 = NOW.strftime("%y%m%d%H%M")
FREEZE_YEAR  = str(NOW.year % 100).zfill(2)
FREEZE_MONTH = str(NOW.month).zfill(2)
FREEZE_DAY   = str(NOW.day).zfill(2)
FREEZE_HOUR  = str(NOW.hour).zfill(2)

def random_meter_address() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(12))

CONCENTRATOR_ADDR = "000000000000"
DEFAULT_PASSWORD   = "00000000"
DEFAULT_OPCODE     = "00000001"

# ── 日志 ──────────────────────────────────────────────────────────────

class TestLogger:
    def __init__(self, proto: str):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"{proto}_{ts}.log"
        self._file = open(self.path, "w", encoding="utf-8")
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def log(self, msg: str = ""):
        self._file.write(msg + "\n"); self._file.flush()

    def header(self, title: str):
        self.log(f"\n{'='*70}")
        self.log(f"  {title}")
        self.log(f"{'='*70}")

    def case(self, name: str, status: str, detail: str = ""):
        s = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}.get(status, "?")
        line = f"  [{s}] {status:4s} | {name}"
        if detail: line += f"  | {detail}"
        self.log(line)
        if status == "PASS": self.passed += 1
        elif status == "FAIL": self.failed += 1
        else: self.skipped += 1

    def summary(self):
        t = self.passed + self.failed + self.skipped
        self.log(f"\n  Total: {t}  |  ✓ Pass: {self.passed}  |  ✗ Fail: {self.failed}  |  ○ Skip: {self.skipped}\n")

    def close(self): self._file.close()


# ── 测试引擎 ──────────────────────────────────────────────────────────

class RoundtripTester:
    def __init__(self, proto: str):
        self.proto = proto
        self.ir = ProtocolIR.from_json_file(str(COMPILED_DIR / f"{proto}.ir.json"))
        self.codecs = create_builtin_registry()
        self.decode_engine = DecodeEngine(self.ir, self.codecs)
        self.build_engine = BuildEngine(self.ir, self.codecs)
        self.logger = TestLogger(proto)

    def test_build_decode(self, case_name: str, message_id: str, values: dict):
        try:
            build_result = self.build_engine.build(values, message_id=message_id)
            frame = build_result.frame
            decode_result = self.decode_engine.decode(frame)
            self.logger.case(case_name, "PASS",
                             f"frame={build_result.frame_hex}")
            return True
        except Exception as e:
            self.logger.case(case_name, "FAIL", str(e))
            self.logger.log(f"    {e}")
            import traceback
            self.logger.log(traceback.format_exc()[-400:])
            return False

    def test_decode_only(self, case_name: str, frame: bytes):
        try:
            self.decode_engine.decode(frame)
            self.logger.case(case_name, "PASS",
                             f"frame={frame.hex(' ').upper()}")
            return True
        except Exception as e:
            self.logger.case(case_name, "FAIL", str(e))
            return False

    def build_dlt645_frame(self, address: str, control: dict, data_bytes: bytes,
                           preamble_count: int = 1) -> bytes:
        preamble = bytes([0xFE]) * preamble_count
        start1 = bytes([0x68])
        addr_text = address.zfill(12)
        addr_bytes = bytes(
            (int(addr_text[i], 16) << 4) | int(addr_text[i+1], 16)
            for i in range(0, 12, 2)
        )[::-1]
        start2 = bytes([0x68])
        ctrl_byte = (control.get("func", 0) & 0x1F)
        if control.get("follow"): ctrl_byte |= 0x20
        if control.get("ack"):    ctrl_byte |= 0x40
        if control.get("dir"):    ctrl_byte |= 0x80
        ctrl_bytes = bytes([ctrl_byte])
        length_byte = bytes([len(data_bytes)])
        cs_val = (sum(start1 + addr_bytes + start2 + ctrl_bytes + length_byte + data_bytes)) & 0xFF
        return (preamble + start1 + addr_bytes + start2 + ctrl_bytes +
                length_byte + data_bytes + bytes([cs_val]) + bytes([0x16]))

    def dlt645_p33(self, logical: bytes) -> bytes:
        return bytes((b + 0x33) & 0xFF for b in logical)

    def build_csg_frame(self, control: dict, user_data: bytes) -> bytes:
        start = bytes([0x68])
        total = 1 + 2 + 1 + len(user_data) + 1 + 1
        total_bytes = total.to_bytes(2, 'little')
        ctrl_byte = 0
        if control.get("dir"): ctrl_byte |= 0x80
        if control.get("prm"): ctrl_byte |= 0x40
        if control.get("add"): ctrl_byte |= 0x20
        ctrl_bytes = bytes([ctrl_byte])
        cs_val = (sum(ctrl_bytes + user_data)) & 0xFF
        return start + total_bytes + ctrl_bytes + user_data + bytes([cs_val]) + bytes([0x16])

    def close(self): self.logger.close()


# ══════════════════════════════════════════════════════════════════════
# DLT645-2007
# ══════════════════════════════════════════════════════════════════════

def test_dlt645():
    t = RoundtripTester("dlt645_2007")
    log = t.logger
    addr = random_meter_address()
    log.header(f"DLT645-2007 往返测试 — 地址: {addr} — {NOW.isoformat()}")

    def ctrl(func, dir=0, ack=0, follow=0):
        return {"func": func, "dir": dir, "ack": ack, "follow": follow}

    def bv(msg_id, length, **fields):
        """构造 build values"""
        vals = {"preamble": 0, "address": addr, "length": length}
        # 从 build plan 推断 control
        plan = t.ir.build_plans.get(msg_id)
        if plan:
            for _, key_str in plan.route_chain:
                kl = json.loads(key_str)
                if len(kl) >= 2:
                    vals["control"] = {"func": kl[0], "dir": kl[1]}
                break
        vals.update(fields)
        return vals

    # ═══════════════════════════ Part A: Build → Decode ═══════════════
    log.header("Part A: Build → Decode (直接往返) — 29 条")

    # 0x08 广播校时: datetime(6B BCD) → data=6
    t.test_build_decode("广播校时请求(0x08)", "broadcast_time_request",
        bv("broadcast_time_request", 6, address="999999999999", preamble=1, datetime=CURRENT_TIME_6))

    # 0x11 读数据: DI(4H) → data=4
    t.test_build_decode("读数据请求(0x11)", "read_data_request",
        bv("read_data_request", 4, preamble=2, di="00010000"))

    # 0x12 读后续: DI(4H) → data=4; follow_data(4B) → data=4
    t.test_build_decode("读后续请求(0x12)", "read_follow_request",
        bv("read_follow_request", 4, di="00010000"))
    t.test_build_decode("读后续应答(0x12)", "read_follow_response",
        bv("read_follow_response", 4, follow_data=bytes([0x11, 0x22, 0x33, 0x44])))

    # 0x13 读地址: reserved(4H) → data=4; address_data(6B BCD) → data=6
    t.test_build_decode("读地址请求(0x13)", "read_address_request",
        bv("read_address_request", 4, address="AAAAAAAAAAAA", preamble=0, reserved="AAAAAAAA"))
    t.test_build_decode("读地址应答(0x13)", "read_address_response",
        bv("read_address_response", 6, address_data=addr))

    # 0x14 写数据: DI(4H)+pa(1H)+p0(1H)+p1(1H)+p2(1H)+opcode(4BCD)+payload(2B) → data=14
    #                             wait - password is a struct with 4 1-byte hex fields = 4 bytes
    t.test_build_decode("写数据请求(0x14)", "write_data_request",
        bv("write_data_request", 14,
           di="00010000",
           password={"pa": "04", "p0": "00", "p1": "00", "p2": "00"},
           operator_code="12345678",
           payload=bytes([0xAA, 0xBB])))
    t.test_build_decode("写数据应答(0x14)", "write_data_response",
        bv("write_data_response", 1, status=0x00))

    # 0x15 写地址: new_addr(6BCD)+password(4H)+opcode(4BCD) → data=14
    t.test_build_decode("写地址请求(0x15)", "write_address_request",
        bv("write_address_request", 14, address=CONCENTRATOR_ADDR,
           new_address=addr, password="00000400", operator_code="00000001"))
    t.test_build_decode("写地址应答(0x15)", "write_address_response",
        bv("write_address_response", 1, status=0x00))

    # 0x16 冻结: freeze_type(4H)+freeze_time(5BCD) → data=9
    t.test_build_decode("冻结命令请求(0x16)", "freeze_request",
        bv("freeze_request", 9, address=CONCENTRATOR_ADDR,
           freeze_type="00010000", freeze_time=CURRENT_TIME_5))
    t.test_build_decode("冻结命令应答(0x16)", "freeze_response",
        bv("freeze_response", 1, status=0x00))

    # 0x17 改速率: baud_rate(1 enum) → data=1
    t.test_build_decode("改速率请求(0x17)", "change_baudrate_request",
        bv("change_baudrate_request", 1, baud_rate=0x04))
    t.test_build_decode("改速率应答(0x17)", "change_baudrate_response",
        bv("change_baudrate_response", 1, status=0x00))

    # 0x18 改密码: password_info(8H) → data=8; new_password(4H) → data=4
    t.test_build_decode("改密码请求(0x18)", "change_password_request",
        bv("change_password_request", 8, password_info="0000000000000000"))
    t.test_build_decode("改密码应答(0x18)", "change_password_response",
        bv("change_password_response", 4, new_password="11111111"))

    # 0x19 需量清零: password(4H)+opcode(4BCD) → data=8
    t.test_build_decode("需量清零请求(0x19)", "clear_demand_request",
        bv("clear_demand_request", 8, password=DEFAULT_PASSWORD, operator_code=DEFAULT_OPCODE))
    t.test_build_decode("需量清零应答(0x19)", "clear_demand_response",
        bv("clear_demand_response", 1, status=0x00))

    # 0x1A 电表清零: password(4H)+opcode(4BCD) → data=8
    t.test_build_decode("电表清零请求(0x1A)", "clear_meter_request",
        bv("clear_meter_request", 8, password=DEFAULT_PASSWORD, operator_code=DEFAULT_OPCODE))
    t.test_build_decode("电表清零应答(0x1A)", "clear_meter_response",
        bv("clear_meter_response", 1, status=0x00))

    # 0x1B 事件清零: event_type(4H)+password(4H)+opcode(4BCD) → data=12
    t.test_build_decode("事件清零请求(0x1B)", "clear_event_request",
        bv("clear_event_request", 12,
           event_type="00000000", password=DEFAULT_PASSWORD, operator_code=DEFAULT_OPCODE))
    t.test_build_decode("事件清零应答(0x1B)", "clear_event_response",
        bv("clear_event_response", 1, status=0x00))

    # 0x1C 跳合闸: control_word(2 bitset)+password(4H)+opcode(4BCD) → data=10
    t.test_build_decode("跳合闸请求(0x1C)", "relay_control_request",
        bv("relay_control_request", 10,
           control_word={"direct_close": 0, "allow_close": 1, "direct_trip": 0,
                         "delay_trip_timeout": 1, "trip_auto_restore": 0,
                         "delay_trip_current": 0, "reserved": 0,
                         "power_protection": 0, "power_protection_release": 0,
                         "alarm": 0, "alarm_release": 0},
           password=DEFAULT_PASSWORD, operator_code=DEFAULT_OPCODE))
    t.test_build_decode("跳合闸应答(0x1C)", "relay_control_response",
        bv("relay_control_response", 2, status="0000"))

    # 0x03 安全认证: auth_type(1 uint8)+auth_data(4B) → data=5
    t.test_build_decode("安全认证请求(0x03)", "security_auth_request",
        bv("security_auth_request", 5, auth_type=1, auth_data=bytes([0x11, 0x22, 0x33, 0x44])))
    t.test_build_decode("安全认证应答(0x03)", "security_auth_response",
        bv("security_auth_response", 4, auth_result="0000", auth_data=bytes([0x55, 0x66])))

    # 0x1D 端子控制: control_word(1 uint8)+password(4H)+opcode(4BCD) → data=9
    t.test_build_decode("端子控制请求(0x1D)", "output_control_request",
        bv("output_control_request", 9, control_word=0x01,
           password=DEFAULT_PASSWORD, operator_code=DEFAULT_OPCODE))
    t.test_build_decode("端子控制应答(0x1D)", "output_control_response",
        bv("output_control_response", 1, status=0x00))

    # ═══════════════════ Part B: DI 变体 (手动帧) ═══════════════════
    log.header("Part B: 读数据应答 DI 变体 (手动帧 → Decode) — 27 个")

    def test_di(name: str, di_hex: str, variant_data: bytes):
        di_wire = bytes.fromhex(di_hex)[::-1]  # LE
        payload = di_wire + variant_data
        data_enc = t.dlt645_p33(payload)
        frame = t.build_dlt645_frame(addr, ctrl(0x11, dir=1), data_enc, 1)
        t.test_decode_only(f"DI={di_hex} {name}", frame)

    test_di("日冻结时间",               "00010000", bytes([0x25, 0x06, 0x21, 0x10]))
    test_di("月冻结时间",               "00010001", bytes([0x25, 0x06, 0x21, 0x10]))
    test_di("正向有功总电能",           "0001FF00", bytes([0x12, 0x34, 0x56, 0x78]))
    test_di("正向有功费率1",            "00010100", bytes([0x11, 0x22, 0x33, 0x44]))
    test_di("正向有功费率2",            "00010200", bytes([0x22, 0x33, 0x44, 0x55]))
    test_di("正向有功费率3",            "00010300", bytes([0x33, 0x44, 0x55, 0x66]))
    test_di("正向有功费率4",            "00010400", bytes([0x44, 0x55, 0x66, 0x77]))
    test_di("反向有功总电能",           "0002FF00", bytes([0x00, 0x11, 0x22, 0x33]))
    test_di("正向无功总电能",           "0003FF00", bytes([0x10, 0x20, 0x30, 0x40]))
    test_di("反向无功总电能",           "0004FF00", bytes([0x00, 0x00, 0x10, 0x20]))
    test_di("正向有功总电能(5字节)",    "0001FF01", bytes([0x12, 0x34, 0x56, 0x78, 0x90]))
    test_di("正向有功总需量",           "0101FF00", bytes([0x12, 0x34, 0x56, 0x78, 0x25, 0x06, 0x21, 0x10, 0x30]))
    # 电压 220V: BCD numeric 0220.0 → bytes: 02 20 (2B)
    test_di("A相电压(220V)",           "02010100", bytes([0x02, 0x20]))
    test_di("B相电压(220V)",           "02010200", bytes([0x02, 0x20]))
    test_di("C相电压(220V)",           "02010300", bytes([0x02, 0x20]))
    # 电流 5A: BCD numeric 005.000 (3B) → bytes: 00 50 00
    test_di("A相电流(5A)",             "02020100", bytes([0x00, 0x50, 0x00]))
    test_di("B相电流(5A)",             "02020200", bytes([0x00, 0x50, 0x00]))
    test_di("C相电流(5A)",             "02020300", bytes([0x00, 0x50, 0x00]))
    test_di("总有功功率",              "02030000", bytes([0x00, 0x05, 0x00]))
    test_di("A相有功功率",             "02030100", bytes([0x00, 0x02, 0x00]))
    test_di("总功率因数",              "02060000", bytes([0x09, 0x50]))
    test_di("电网频率",                "03020000", bytes([0x50, 0x00]))
    test_di("电表通信地址",            "04000401", bytes.fromhex(addr)[::-1])
    test_di("电表运行状态字1",         "04000501", bytes([0x00, 0x00]))
    test_di("当前日期时间",            "04000101", bytes([0x25, 0x06, 0x21, 0x10, 0x30, 0x00]))
    test_di("日冻结正向有功电能",      "0501FF00", bytes([0x12, 0x34, 0x56, 0x78]))
    test_di("负荷记录块",              "04060001", bytes([0x02, 0x01, 0x02, 0x03]))

    log.summary(); t.close(); return log


# ══════════════════════════════════════════════════════════════════════
# CSG-2016
# ══════════════════════════════════════════════════════════════════════

def test_csg():
    t = RoundtripTester("csg_2016")
    log = t.logger
    log.header(f"CSG-2016 往返测试 — {NOW.isoformat()}")

    def ctrl_csg(dir=0, prm=1, add=0):
        return {"dir": dir, "prm": prm, "add": add}

    def ud(afn: int, seq: int, di: str, payload: bytes = b"") -> bytes:
        """构造 user_data: AFN(1)+SEQ(1)+DI(4 LE)+payload"""
        return bytes([afn, seq]) + bytes.fromhex(di)[::-1] + payload

    # CSG DI 编码: DI3 DI2 DI1 DI0 (逻辑序, 大端显示)
    # DI3=E8(集中器), DI2=dir(0=下行,1=上行), DI1=AFN, DI0=子类型
    def di_csg(afn: int, fn: int = 1, di2: int = 0) -> str:
        """CSG DI (协议表4): DI3=E8 DI2=类型 DI1=AFN DI0=Fn
        DI2: 00=上下行无下行数据 01=上下行格式一致 02=仅下行/上行确认否认
             03=仅下行带数据 04=仅上行带数据 05=仅上行/下行确认 06=上下行无上行数据"""
        return f"E8{di2:02X}{afn:02X}{fn:02X}"

    def tf(name: str, control: dict, user_data: bytes):
        frame = t.build_csg_frame(control, user_data)
        t.test_decode_only(name, frame)

    # ── 下行 (主站→终端, dir=0, prm=1) ──
    log.header("下行报文 (主站→终端, dir=0) — 7 条")

    # AFN=00 确认: DI2=01 Fn=1 (E8010001)
    tf("AFN=00 确认(下行)",    ctrl_csg(0,1,0), ud(0x00, 1, di_csg(0x00, 1, 1), bytes([0x00])))
    # AFN=01 复位硬件: DI2=02 Fn=1 (E8020101)
    tf("AFN=01 复位硬件(下行)", ctrl_csg(0,1,0), ud(0x01, 1, di_csg(0x01, 1, 2), bytes([0x00])))
    # AFN=02 添加任务: DI2=02 Fn=1 (E8020201)
    tf("AFN=02 添加任务(下行)", ctrl_csg(0,1,0), ud(0x02, 2, di_csg(0x02, 1, 2),
        bytes([0x12,0x34,0x56,0x78,0x90,0x12, 0x00])))  # 任务参数示例
    # AFN=03 查询厂商代码: DI2=00 Fn=1 (E8000301) — 无请求体
    tf("AFN=03 查询厂商(下行)", ctrl_csg(0,1,0), ud(0x03, 3, di_csg(0x03, 1, 0)))
    # AFN=04 允许上报事件: DI2=02 Fn=4 (E8020404)
    tf("AFN=04 允许上报(下行)", ctrl_csg(0,1,0), ud(0x04, 4, di_csg(0x04, 4, 2), bytes([0x01])))
    # AFN=05 上报任务状态: DI2=05 Fn=5 (E8050505) — 上报类，上行报文
    # (下行无 AFN=05 请求)
    # AFN=06 请求集中器时间: DI2=06 Fn=1 (E8060601)
    tf("AFN=06 请求时间(下行)", ctrl_csg(0,1,0), ud(0x06, 6, di_csg(0x06, 1, 6)))
    # AFN=07 查询文件信息: DI2=00 Fn=3 (E8000703)
    tf("AFN=07 查询文件(下行)", ctrl_csg(0,1,0), ud(0x07, 7, di_csg(0x07, 3, 0)))

    # ── 上行 (dir=1, prm=0) ──
    log.header("上行报文 (终端→主站, dir=1) — 9 条")

    tf("AFN=00 确认(上行)",       ctrl_csg(1,0,0), ud(0x00, 1, di_csg(0x00, 1, 1), bytes([0x00])))
    tf("AFN=00 否认(上行)",       ctrl_csg(1,0,0), ud(0x00, 1, di_csg(0x00, 1, 1), bytes([0x01, 0x01])))
    tf("AFN=01 初始化应答(上行)", ctrl_csg(1,0,0), ud(0x01, 1, di_csg(0x01, 1, 2), bytes([0x00])))
    tf("AFN=02 转发应答(上行)",   ctrl_csg(1,0,0), ud(0x02, 2, di_csg(0x02, 1, 2),
        bytes([0x12,0x34,0x56,0x78,0x90,0x12]) + bytes([0xFE,0xFE,0x68])))
    tf("AFN=03 厂家信息(上行)",   ctrl_csg(1,0,0), ud(0x03, 3, di_csg(0x03, 1, 0),
        bytes([0x01, 0x01,0x23,0x45,0x67]) + b"HW_VER_1" + b"SW_VER_1" + bytes([0x01])))
    # AFN=04 上行为确认/否认 (DI2=02 → 上行确认)
    # AFN=04 写参数确认 (DI=E8020404, Fn=4=允许/禁止上报)
    tf("AFN=04 写参数确认(上行)", ctrl_csg(1,0,0), ud(0x04, 4, di_csg(0x04, 4, 2), bytes([0x00, 0x00])))
    # AFN=05 上报任务数据 (DI2=05 Fn=1)
    tf("AFN=05 上报任务(上行)",   ctrl_csg(1,0,0), ud(0x05, 5, di_csg(0x05, 1, 5),
        bytes([0x12,0x34,0x56,0x78,0x90,0x12, 0x00,0x11,0x22,0x33])))
    # AFN=06 集中器时间应答 (DI2=01 Fn=1  — 上下行格式一致)
    tf("AFN=06 时间应答(上行)",   ctrl_csg(1,0,0), ud(0x06, 6, di_csg(0x06, 1, 1),
        bytes.fromhex(CURRENT_TIME_6)))
    # AFN=07 文件传输进度 (DI2=00 Fn=4)
    # AFN=07 查询文件处理进度 (DI=E8000704, DI2=00)
    tf("AFN=07 文件进度(上行)",   ctrl_csg(1,0,0), ud(0x07, 7, di_csg(0x07, 4, 0), bytes([0x50])))

    # ── 带地址域 (add=1) ──
    log.header("带地址域 (add=1) — 2 条")
    asrc = bytes([0x12,0x34,0x56,0x78,0x90,0x12])
    adst = bytes([0x00,0x00,0x00,0x00,0x00,0x00])
    # AFN=03 查询厂商(带地址): DI2=00 Fn=1 (E8000301)
    tf("AFN=03 查询厂商(带地址)", ctrl_csg(0,1,1), asrc + adst + ud(0x03, 1, di_csg(0x03, 1, 0)))
    # AFN=00 确认(带地址): DI2=01 Fn=1
    tf("AFN=00 确认(带地址)",     ctrl_csg(1,0,1), adst + asrc + ud(0x00, 1, di_csg(0x00, 1, 1), bytes([0x00])))

    log.summary(); t.close(); return log


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  全量报文 Build → Decode 往返测试")
    print("=" * 60)

    dlt_ir = ProtocolIR.from_json_file(str(COMPILED_DIR / "dlt645_2007.ir.json"))
    csg_ir = ProtocolIR.from_json_file(str(COMPILED_DIR / "csg_2016.ir.json"))
    total = len(dlt_ir.build_plans) + len(dlt_ir.leaves) + len(csg_ir.build_plans) + len(csg_ir.leaves)
    print(f"\n  DLT645-2007: {len(dlt_ir.build_plans)} 消息 + {len(dlt_ir.leaves)} 变体")
    print(f"  CSG-2016:    {len(csg_ir.build_plans)} 消息 + {len(csg_ir.leaves)} 变体")
    print(f"  总计: {total} 个定义")
    print(f"  日志目录: {LOG_DIR}")

    from protocol_tool.compiler.pipeline import compile_protocol
    reg = str(_project_root / "protocol_tool" / "protocols" / "registry.yaml")
    compile_protocol(reg, "dlt645_2007", output_dir=str(COMPILED_DIR))
    compile_protocol(reg, "csg_2016", output_dir=str(COMPILED_DIR))

    print(f"\n  [1/2] Testing DLT645-2007...")
    dl = test_dlt645()
    print(f"  DLT645: {dl.passed} pass, {dl.failed} fail, {dl.skipped} skip")

    print(f"\n  [2/2] Testing CSG-2016...")
    cl = test_csg()
    print(f"  CSG:    {cl.passed} pass, {cl.failed} fail, {cl.skipped} skip")

    print(f"\n  日志:")
    print(f"    {dl.path}")
    print(f"    {cl.path}")
    print(f"{'='*60}")
