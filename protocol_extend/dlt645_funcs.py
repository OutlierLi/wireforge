"""DL/T 645-2007 FUNC registry for protocol_extend."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dlt645FuncDef:
    func: int
    router: str
    selector_field: str = "di"
    default_dir: int = 1
    builtin: bool = True
    description: str = ""
    pair_resp_dir: int = 1

    @property
    def default_dir_name(self) -> str:
        return "downlink" if self.default_dir == 0 else "uplink"


# builtin=True: router 已在 protocol.yaml + message routed_payload 中注册
DLT645_FUNC_REGISTRY: dict[int, Dlt645FuncDef] = {
    0x03: Dlt645FuncDef(0x03, "security_auth_request_body", default_dir=0, builtin=False, description="安全认证"),
    0x08: Dlt645FuncDef(0x08, "broadcast_time_request_body", default_dir=0, builtin=False, description="广播校时"),
    0x11: Dlt645FuncDef(0x11, "read_data_response_di", default_dir=1, builtin=True, description="读数据应答"),
    0x12: Dlt645FuncDef(0x12, "read_follow_response_body", default_dir=1, builtin=False, description="读后续数据应答"),
    0x13: Dlt645FuncDef(0x13, "read_address_response_body", default_dir=1, builtin=False, description="读通信地址应答"),
    0x14: Dlt645FuncDef(0x14, "write_data_request_di", default_dir=0, builtin=True, description="写数据请求载荷"),
    0x16: Dlt645FuncDef(
        0x16, "freeze_request_di", selector_field="freeze_type", default_dir=0, builtin=True, description="冻结命令",
    ),
    0x17: Dlt645FuncDef(0x17, "change_baudrate_request_body", default_dir=0, builtin=False, description="更改通信速率"),
    0x18: Dlt645FuncDef(0x18, "change_password_request_body", default_dir=0, builtin=False, description="修改密码"),
    0x19: Dlt645FuncDef(0x19, "clear_demand_request_body", default_dir=0, builtin=False, description="最大需量清零"),
    0x1A: Dlt645FuncDef(0x1A, "clear_meter_request_body", default_dir=0, builtin=False, description="电表清零"),
    0x1B: Dlt645FuncDef(
        0x1B, "clear_event_request_di", selector_field="event_type", default_dir=0, builtin=True, description="事件清零",
    ),
    0x1C: Dlt645FuncDef(0x1C, "relay_control_request_body", default_dir=0, builtin=False, description="跳合闸控制"),
    0x1D: Dlt645FuncDef(0x1D, "output_control_request_body", default_dir=0, builtin=False, description="多功能端子输出"),
}

DEFAULT_DLT645_FUNC = 0x11


def get_dlt645_func(func: int | None) -> Dlt645FuncDef | None:
    if func is None:
        return DLT645_FUNC_REGISTRY.get(DEFAULT_DLT645_FUNC)
    return DLT645_FUNC_REGISTRY.get(func)


def resolve_dlt645_func(func: int | None) -> Dlt645FuncDef:
    resolved = get_dlt645_func(func)
    if resolved is None:
        code = func if func is not None else DEFAULT_DLT645_FUNC
        return Dlt645FuncDef(
            func=code,
            router=f"func_{code:02x}_di_router",
            default_dir=1,
            builtin=False,
            description=f"FUNC 0x{code:02X}",
        )
    return resolved


def list_dlt645_funcs() -> list[Dlt645FuncDef]:
    return [DLT645_FUNC_REGISTRY[k] for k in sorted(DLT645_FUNC_REGISTRY)]
