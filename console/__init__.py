"""WireForge 命令行接口 — 命令定义 + 处理器 + 公共 API。

用法:
    from console.api import exec_cmd, list_cmds
    result = exec_cmd("build", {"proto": "dlt645", "func": "0x11"})
"""

from console.api import exec_cmd, list_cmds, get_cmd
from console.handler import CmdResult
from console.command import registry, Command, Param
