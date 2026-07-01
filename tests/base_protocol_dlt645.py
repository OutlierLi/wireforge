"""DL/T 645-2007 protocol_extend 测试用例 — 覆盖全部 FUNC 与典型 DI 载荷."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from protocol_extend.dlt645_funcs import resolve_dlt645_func

ROOT = Path(__file__).resolve().parent.parent
C_STRUCT_DIR = ROOT / "tests" / "fixtures" / "c_struct" / "dlt645"


def test_di_for_func(func: int, *, seq: int = 1) -> str:
    """8 位测试 DI：0099{func}{seq}，避免与内置 DI 冲突。"""
    return f"0099{func:02X}{seq:02X}"


@dataclass(frozen=True)
class FieldCheck:
    name: str
    type: str


@dataclass(frozen=True)
class Dlt645ExtendCase:
    func: int
    name: str
    description: str
    c_struct_path: str
    di: str = ""
    seq: int = 1
    dir: int | None = None
    field_checks: tuple[FieldCheck, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.di:
            object.__setattr__(self, "di", test_di_for_func(self.func, seq=self.seq))

    @property
    def func_def(self):
        return resolve_dlt645_func(self.func)

    @property
    def router(self) -> str:
        return self.func_def.router

    @property
    def selector_field(self) -> str:
        return self.func_def.selector_field

    @property
    def builtin(self) -> bool:
        return self.func_def.builtin

    @property
    def c_struct_file(self) -> Path:
        return Path(self.c_struct_path)


def _p(name: str) -> str:
    return str(C_STRUCT_DIR / name)


# ── 全部 FUNC（对应 protocol_info.DLT645_MESSAGES）────────────────────────

DLT645_EXTEND_CASES: tuple[Dlt645ExtendCase, ...] = (
    Dlt645ExtendCase(
        func=0x03, name="security_auth",
        description="安全认证扩展载荷",
        c_struct_path=_p("func_03_security_auth.h"),
        field_checks=(FieldCheck("auth_type", "enum"), FieldCheck("auth_data", "hex")),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x08, name="broadcast_time",
        description="广播校时扩展",
        c_struct_path=_p("func_08_broadcast_time.h"),
        dir=0,
        field_checks=(FieldCheck("clock", "bcd_datetime"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x11, name="read_data_energy",
        description="读数据应答-电能量",
        c_struct_path=_p("func_11_read_data_energy.h"),
        field_checks=(
            FieldCheck("rate_index", "enum"),
            FieldCheck("energy_raw", "uint32_le"),
        ),
        tags=("message", "builtin", "di_routed"),
    ),
    Dlt645ExtendCase(
        func=0x11, name="read_data_voltage", seq=2,
        description="读数据应答-电压",
        c_struct_path=_p("func_11_read_data_voltage.h"),
        di=test_di_for_func(0x11, seq=2),
        field_checks=(FieldCheck("voltage", "bcd"),),
        tags=("message", "builtin", "di_routed"),
    ),
    Dlt645ExtendCase(
        func=0x11, name="read_data_datetime", seq=3,
        description="读数据应答-日期时间",
        c_struct_path=_p("func_11_read_data_datetime.h"),
        di=test_di_for_func(0x11, seq=3),
        field_checks=(FieldCheck("datetime", "struct"),),
        tags=("message", "builtin", "di_routed", "nested_bcd"),
    ),
    Dlt645ExtendCase(
        func=0x12, name="read_follow",
        description="读后续数据应答扩展",
        c_struct_path=_p("func_12_read_follow.h"),
        field_checks=(FieldCheck("follow_data", "hex"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x13, name="read_address",
        description="读通信地址应答扩展",
        c_struct_path=_p("func_13_read_address.h"),
        field_checks=(FieldCheck("meter_address", "bcd"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x14, name="write_data",
        description="写数据请求载荷扩展",
        c_struct_path=_p("func_14_write_data.h"),
        dir=0,
        field_checks=(FieldCheck("write_value", "uint16_le"),),
        tags=("message", "builtin", "di_routed"),
    ),
    Dlt645ExtendCase(
        func=0x15, name="write_address",
        description="写通信地址扩展",
        c_struct_path=_p("func_15_write_address.h"),
        dir=0,
        field_checks=(FieldCheck("confirm_code", "enum"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x16, name="freeze",
        description="冻结命令扩展",
        c_struct_path=_p("func_16_freeze.h"),
        dir=0,
        field_checks=(FieldCheck("freeze_time", "bcd_datetime"),),
        tags=("message", "builtin", "freeze_type"),
    ),
    Dlt645ExtendCase(
        func=0x17, name="change_baudrate",
        description="更改通信速率扩展",
        c_struct_path=_p("func_17_change_baudrate.h"),
        dir=0,
        field_checks=(FieldCheck("baud_rate", "enum"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x18, name="change_password",
        description="修改密码扩展",
        c_struct_path=_p("func_18_change_password.h"),
        dir=0,
        field_checks=(FieldCheck("password_block", "struct"),),
        tags=("message", "nested"),
    ),
    Dlt645ExtendCase(
        func=0x19, name="clear_demand",
        description="最大需量清零扩展",
        c_struct_path=_p("func_19_clear_demand.h"),
        dir=0,
        field_checks=(FieldCheck("demand_slot", "uint8"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x1A, name="clear_meter",
        description="电表清零扩展",
        c_struct_path=_p("func_1a_clear_meter.h"),
        dir=0,
        field_checks=(FieldCheck("clear_flag", "enum"),),
        tags=("message",),
    ),
    Dlt645ExtendCase(
        func=0x1B, name="clear_event",
        description="事件清零扩展载荷",
        c_struct_path=_p("func_1b_clear_event.h"),
        dir=0,
        field_checks=(FieldCheck("event_data", "hex"),),
        tags=("message", "builtin", "event_type"),
    ),
    Dlt645ExtendCase(
        func=0x1C, name="relay_control",
        description="跳合闸控制扩展",
        c_struct_path=_p("func_1c_relay_control.h"),
        dir=0,
        field_checks=(FieldCheck("control_bits", "struct"),),
        tags=("message", "nested"),
    ),
    Dlt645ExtendCase(
        func=0x1D, name="output_control",
        description="多功能端子输出扩展",
        c_struct_path=_p("func_1d_output_control.h"),
        dir=0,
        field_checks=(FieldCheck("output_mode", "enum"),),
        tags=("message",),
    ),
)

BUILTIN_COMPILE_CASES = tuple(c for c in DLT645_EXTEND_CASES if c.builtin)
# 每个内置 router 只跑一次真实 compile，避免重复编译
REAL_COMPILE_CASES = tuple(
    next(c for c in BUILTIN_COMPILE_CASES if c.func == func)
    for func in (0x11, 0x14, 0x16, 0x1B)
)
MESSAGE_CASES = tuple(c for c in DLT645_EXTEND_CASES if "message" in c.tags)
