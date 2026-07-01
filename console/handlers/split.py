"""/split 命令处理器 — 打开新终端窗口/分屏/标签页，继承当前会话状态。

支持的终端:
  - macOS: iTerm2, Terminal.app
  - 跨平台: tmux, VS Code, WezTerm
  - Linux: GNOME Terminal, Konsole
  - Windows: Windows Terminal, PowerShell
  - 通用兜底: 打印启动命令

用法:
  /split                  → 默认开新 tab
  /split --mode=split     → 竖直分屏
  /split --mode=window    → 新窗口
  /split --mode=tab       → 新标签页
  /split --dry-run        → 仅打印命令，不实际启动
"""

from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from console.response import ok, fail

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = ROOT / "log"


def _state_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"session_state_{timestamp}.yaml"


def _build_launch_command(state_path: Path) -> list[str]:
    """构建启动 wireforge-terminal 的命令行参数。"""
    entry = ROOT / "console" / "terminal.py"
    return [
        sys.executable,
        str(entry),
        "--restore-state", str(state_path),
    ]


# ── 终端检测 ──────────────────────────────────────────────────────────

def _detect_terminal() -> str:
    """检测当前终端环境，返回终端标识符。

    检测顺序: 环境变量 → 进程特征 → 平台兜底
    """
    term_program = os.environ.get("TERM_PROGRAM", "")
    term = os.environ.get("TERM", "")

    # macOS 专用：iTerm2 通过 TERM_PROGRAM 自报身份
    if term_program == "iTerm.app":
        return "iterm2"
    if term_program == "Apple_Terminal":
        return "apple_terminal"

    # kitty — TERM 通常为 "xterm-kitty"
    if "kitty" in term.lower() or os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"

    # tmux（多平台）
    if os.environ.get("TMUX"):
        return "tmux"

    # VS Code
    if term_program == "vscode" or "VSCODE" in os.environ.get("TERM_PROGRAM", ""):
        return "vscode"
    if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_IPC_HOOK_CLI"):
        return "vscode"

    # WezTerm
    if term_program == "WezTerm" or "wezterm" in os.environ.get("TERM_PROGRAM", "").lower():
        return "wezterm"

    # Windows Terminal
    if os.environ.get("WT_SESSION"):
        return "windows_terminal"

    # JetBrains
    if os.environ.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        return "jetbrains"

    # Linux 终端
    if os.environ.get("KONSOLE_VERSION"):
        return "konsole"
    if "GNOME_TERMINAL" in term:
        return "gnome_terminal"
    if os.environ.get("GNOME_TERMINAL_SERVICE"):
        return "gnome_terminal"

    # Windows 兜底
    if platform.system() == "Windows":
        return "windows"

    # macOS: 最后手段 — 检查哪个终端应用在运行
    if platform.system() == "Darwin":
        running = _running_macos_terminals()
        if "iTerm2" in running and "Terminal" not in running:
            return "iterm2"
        # 默认用 Terminal.app（macOS 自带，始终可用）
        return "apple_terminal"

    return "generic"


def _running_macos_terminals() -> set[str]:
    """返回当前在 macOS 上运行的终端应用名集合。"""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to return name of every process '
             'whose name contains "Terminal" or name contains "iTerm" or name contains "kitty"'],
            capture_output=True, text=True, timeout=3,
        )
        names = {n.strip() for n in r.stdout.split(",") if n.strip()}
        return names
    except Exception:
        return set()


# ── 启动器 ────────────────────────────────────────────────────────────

def _launch(cmd_parts: list[str], cwd: Path, wait: bool = False) -> bool:
    """执行启动命令，返回是否成功。

    wait=False: fire-and-forget（用于打开新终端窗口，进程不会立即退出）
    wait=True:  等待进程结束并检查退出码（用于 kitty @ 等 RPC 命令）
    """
    try:
        p = subprocess.Popen(cmd_parts, cwd=cwd,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if wait:
            stdout, stderr = p.communicate(timeout=10)
            return p.returncode == 0
        return True
    except OSError:
        return False
    except subprocess.TimeoutExpired:
        p.kill()
        return False


def _launch_iterm2(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 AppleScript 启动 iTerm2。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)

    if mode == "split":
        script = (
            f'tell application "iTerm2"\n'
            f'  tell current session of current window\n'
            f'    set s to split vertically with default profile\n'
            f'    tell s to write text "{command_str}"\n'
            f'  end tell\n'
            f'end tell'
        )
    elif mode == "tab":
        script = (
            f'tell application "iTerm2"\n'
            f'  tell current window\n'
            f'    set t to create tab with default profile\n'
            f'    tell current session of t to write text "{command_str}"\n'
            f'  end tell\n'
            f'end tell'
        )
        # 先尝试规范语法，失败则用简单版
        if not _try_osascript(script):
            script = (
                f'tell application "iTerm2"\n'
                f'  tell current window\n'
                f'    create tab with default profile\n'
                f'    tell current session to write text "{command_str}"\n'
                f'  end tell\n'
                f'end tell'
            )
    else:  # window
        script = (
            f'tell application "iTerm2"\n'
            f'  set w to create window with default profile\n'
            f'  tell current session of w to write text "{command_str}"\n'
            f'end tell'
        )
        if not _try_osascript(script):
            script = (
                f'tell application "iTerm2"\n'
                f'  create window with default profile\n'
                f'  tell current session of current window to write text "{command_str}"\n'
                f'end tell'
            )
    return _launch(["osascript", "-e", script], cwd)


def _try_osascript(script: str) -> bool:
    """Check if an AppleScript compiles without error (dry-run)."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _launch_apple_terminal(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 AppleScript 启动 Terminal.app。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)
    cd_str = f"cd {shlex.quote(str(cwd))} && "

    if mode == "window":
        script = (
            f'tell application "Terminal"\n'
            f'  do script "{cd_str}{command_str}"\n'
            f'end tell'
        )
    else:  # tab — Terminal.app 没有直接 API，通过 System Events 模拟 Cmd+T
        script = (
            f'tell application "Terminal" to activate\n'
            f'tell application "System Events"\n'
            f'  keystroke "t" using command down\n'
            f'end tell\n'
            f'delay 0.3\n'
            f'tell application "Terminal"\n'
            f'  do script "{cd_str}{command_str}" in front window\n'
            f'end tell'
        )
    return _launch(["osascript", "-e", script], cwd)


def _launch_tmux(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 tmux 命令启动。"""
    command_str = " ".join(wireforge_cmd)
    cd_str = f"cd {shlex.quote(str(cwd))} && "
    full_cmd = f"{cd_str}{command_str}"

    if mode == "split":
        return _launch(["tmux", "split-window", "-h", full_cmd], cwd)
    else:  # tab (new-window)
        return _launch(["tmux", "new-window", full_cmd], cwd)


def _launch_vscode(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """VS Code 不支持内建终端分屏，尝试新窗口。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)
    if mode == "window":
        # 在新 VS Code 窗口中打开
        return _launch(["code", "--new-window", "--goto",
                        str(ROOT / "console" / "terminal.py")], cwd)
    # tab/split: VS Code 内建终端不支持，打印命令
    return False


def _launch_wezterm(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 wezterm cli 启动。"""
    command_str = " ".join(wireforge_cmd)
    if mode == "split":
        return _launch(["wezterm", "cli", "split-pane", "--", "sh", "-c", command_str], cwd)
    elif mode == "tab":
        return _launch(["wezterm", "cli", "spawn", "--new-tab", "--", "sh", "-c", command_str], cwd)
    else:  # window
        return _launch(["wezterm", "cli", "spawn", "--", "sh", "-c", command_str], cwd)


def _launch_windows_terminal(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 Windows Terminal (wt) 启动。"""
    command_str = " ".join(wireforge_cmd)
    if mode == "split":
        return _launch(["wt", "-w", "0", "split-pane", "-H",
                        "-d", str(cwd), "--"] + wireforge_cmd, cwd)
    elif mode == "tab":
        return _launch(["wt", "-w", "0", "new-tab",
                        "-d", str(cwd), "--"] + wireforge_cmd, cwd)
    else:  # window
        return _launch(["wt", "-d", str(cwd), "--"] + wireforge_cmd, cwd)


def _launch_gnome_terminal(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 GNOME Terminal 启动。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)
    if mode == "window":
        return _launch(["gnome-terminal", "--working-directory", str(cwd),
                        "--", "bash", "-c", f"{command_str}; exec bash"], cwd)
    elif mode == "tab":
        return _launch(["gnome-terminal", "--tab", "--working-directory", str(cwd),
                        "--", "bash", "-c", f"{command_str}; exec bash"], cwd)
    return False  # GNOME Terminal 不支持 split


def _launch_konsole(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 Konsole 启动。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)
    if mode == "window":
        return _launch(["konsole", "--workdir", str(cwd), "-e",
                        "bash", "-c", f"{command_str}; exec bash"], cwd)
    elif mode == "tab":
        return _launch(["konsole", "--new-tab", "--workdir", str(cwd), "-e",
                        "bash", "-c", f"{command_str}; exec bash"], cwd)
    return False


def _launch_kitty(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通过 kitty @ remote control 启动。

    kitty @ 是 RPC 命令，立即退出 → 用 wait=True 检查退出码。
    失败时返回 False，由 handle() 统一回退链处理。
    需在 kitty 配置中启用 allow_remote_control yes。
    """
    if mode == "split":
        return _launch(["kitty", "@", "launch", "--location", "hsplit",
                        "--cwd", str(cwd), "--"] + wireforge_cmd, cwd, wait=True)
    elif mode == "tab":
        return _launch(["kitty", "@", "new-window",
                        "--cwd", str(cwd), "--"] + wireforge_cmd, cwd, wait=True)
    elif mode == "window":
        return _launch(["kitty", "@", "launch", "--type", "os-window",
                        "--cwd", str(cwd), "--"] + wireforge_cmd, cwd, wait=True)
    return False


def _launch_windows(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """Windows 通用启动 (PowerShell)。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)
    if mode == "split":
        # 尝试 wt
        result = _launch_windows_terminal(mode, wireforge_cmd, cwd)
        if result:
            return result
    # 兜底：新 PowerShell 窗口
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(
            ["powershell", "-NoExit", "-Command",
             f"Set-Location '{cwd}'; {command_str}"],
            cwd=cwd, creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def _launch_generic(mode: str, wireforge_cmd: list[str], cwd: Path) -> bool:
    """通用兜底 — 尝试 x-terminal-emulator 或直接 Popen。"""
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)

    # 尝试 x-terminal-emulator (Linux 通用)
    try:
        subprocess.Popen(
            ["x-terminal-emulator", "-e", f"cd {shlex.quote(str(cwd))} && {command_str}"],
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        pass

    # 最后尝试 open (macOS)
    if platform.system() == "Darwin":
        try:
            subprocess.Popen(["open", "-a", "Terminal", "--"] + wireforge_cmd,
                             cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass

    return False


# ── 终端启动表 ────────────────────────────────────────────────────────

_LAUNCHERS = {
    "iterm2": _launch_iterm2,
    "apple_terminal": _launch_apple_terminal,
    "kitty": _launch_kitty,
    "tmux": _launch_tmux,
    "vscode": _launch_vscode,
    "wezterm": _launch_wezterm,
    "windows_terminal": _launch_windows_terminal,
    "jetbrains": _launch_generic,
    "konsole": _launch_konsole,
    "gnome_terminal": _launch_gnome_terminal,
    "windows": _launch_windows,
    "generic": _launch_generic,
}

_CAPABILITIES = {
    "iterm2": {"split": True, "tab": True, "window": True},
    "apple_terminal": {"split": False, "tab": True, "window": True},
    "kitty": {"split": True, "tab": True, "window": True},
    "tmux": {"split": True, "tab": True, "window": False},
    "vscode": {"split": False, "tab": False, "window": True},
    "wezterm": {"split": True, "tab": True, "window": True},
    "windows_terminal": {"split": True, "tab": True, "window": True},
    "jetbrains": {"split": False, "tab": False, "window": False},
    "konsole": {"split": False, "tab": True, "window": True},
    "gnome_terminal": {"split": False, "tab": True, "window": True},
    "windows": {"split": True, "tab": True, "window": True},
    "generic": {"split": False, "tab": False, "window": False},
}


# ── Handler ────────────────────────────────────────────────────────────

def handle(args: dict[str, Any]) -> dict:
    """执行 /split 命令。

    args:
      mode: "split" | "tab" | "window" (默认 tab)
      dry_run: bool — 仅打印命令不执行
    """
    mode = str(args.get("mode", "tab")).lower()
    if mode not in ("split", "tab", "window"):
        mode = "tab"

    dry_run = bool(args.get("dry_run") or args.get("dry-run"))

    # 1. 导出会话状态
    state_path = _state_path()
    from console.session import export_session
    export_session(state_path)

    # 2. 构建启动命令
    wireforge_cmd = _build_launch_command(state_path)
    cwd = ROOT

    # 3. 检测终端
    terminal = _detect_terminal()

    # 4. 检查能力并降级
    caps = _CAPABILITIES.get(terminal, _CAPABILITIES["generic"])
    effective_mode = mode
    if not caps.get(mode, False):
        # 降级策略: split → tab → window → fallback
        fallback_order = ["split", "tab", "window"]
        for fallback in fallback_order:
            if caps.get(fallback, False):
                effective_mode = fallback
                break
        else:
            effective_mode = "fallback"

    # 5. 启动
    launcher = _LAUNCHERS.get(terminal, _launch_generic)
    launched = False
    if not dry_run:
        launched = launcher(effective_mode, wireforge_cmd, cwd)

    # 如果主终端启动失败，尝试 macOS 兜底
    launch_method = terminal
    if not launched and not dry_run and platform.system() == "Darwin" and terminal not in ("apple_terminal", "generic"):
        launched = _launch_apple_terminal(effective_mode, wireforge_cmd, cwd)
        if launched:
            launch_method = "apple_terminal"

    # 最后尝试 generic
    if not launched and not dry_run:
        launched = _launch_generic(effective_mode, wireforge_cmd, cwd)
        if launched:
            launch_method = "generic"

    # 6. 构建启动命令的可读表示
    command_str = " ".join(shlex.quote(p) for p in wireforge_cmd)

    return ok({
        "state": str(state_path),
        "terminal": terminal,
        "launched_by": launch_method,
        "mode": effective_mode,
        "requested_mode": mode,
        "launched": launched,
        "dry_run": dry_run,
        "command": command_str,
        "hint": f"cd {shlex.quote(str(cwd))} && {command_str}",
    })
