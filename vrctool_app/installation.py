from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from vrctool_app.config_store import app_data_root, app_root
from vrctool_app.single_instance import read_running_instance


SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102


class InstallationError(RuntimeError):
    pass


def find_uninstaller() -> Optional[Path]:
    root = app_root()
    candidates = list(root.glob("unins*.exe"))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def stop_running_instance(timeout: float = 15.0) -> None:
    running = read_running_instance() or {}
    pid = int(running.get("pid") or 0)
    url = str(running.get("url") or "").rstrip("/")
    if url:
        try:
            request = Request(f"{url}/api/app/shutdown", data=b"", method="POST")
            with urlopen(request, timeout=3):
                pass
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    while process_is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.2)


def powershell_path() -> Path:
    return (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def uninstall_helper_path() -> Path:
    return app_data_root() / f"uninstall-helper-{os.getpid()}.ps1"


def launch_uninstaller(silent: bool = False) -> Path:
    if os.name != "nt":
        raise InstallationError("自动卸载仅支持 Windows 安装版")
    uninstaller = find_uninstaller()
    if uninstaller is None:
        raise InstallationError("未找到 Inno Setup 卸载程序，请从 Windows 设置中卸载")
    stop_running_instance()
    powershell = powershell_path()
    if not powershell.is_file():
        raise InstallationError("找不到 Windows PowerShell，无法启动卸载程序")
    quoted_uninstaller = str(uninstaller).replace("'", "''")
    start_command = f"Start-Process -FilePath '{quoted_uninstaller}'"
    if silent:
        start_command += " -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')"
    helper_path = uninstall_helper_path()
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"while (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{\n"
        "  Start-Sleep -Milliseconds 200\n"
        "}\n"
        "Start-Sleep -Milliseconds 1500\n"
        "try {\n"
        f"  {start_command}\n"
        "} finally {\n"
        "  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
        "}\n",
        encoding="utf-8-sig",
    )
    creation_flags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    try:
        subprocess.Popen(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        helper_path.unlink(missing_ok=True)
        raise InstallationError(f"无法启动卸载程序：{exc}") from exc
    return uninstaller
