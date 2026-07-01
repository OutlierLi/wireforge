"""CSG-specific router tables (used by schema + profiles)."""

from __future__ import annotations

AFN00_NO_DIR = 0x00

AFN_ROUTERS: dict[int, str] = {
    0x00: "afn00_di_router",
    0x01: "afn01_di_router",
    0x02: "afn02_di_router",
    0x03: "afn03_di_router",
    0x04: "afn04_di_router",
    0x05: "afn05_di_router",
    0x06: "afn06_di_router",
    0x07: "afn07_di_router",
}


def afn_di_router_id(afn: int) -> str:
    return AFN_ROUTERS.get(afn) or f"afn{afn:02x}_di_router"


def afn_has_builtin_router(afn: int | None) -> bool:
    return afn is not None and afn in AFN_ROUTERS


def router_compile_hint(afn: int) -> str:
    router = afn_di_router_id(afn)
    return (
        f"AFN {afn:02X} 尚无内置 router；扩展 YAML 已写入 extensions/。"
        f"请在 protocol.yaml 添加 {router}（及 afn_router 分组）后运行 bootstrap。"
    )
