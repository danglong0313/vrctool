from __future__ import annotations

import ctypes
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from vrctool_app.config_store import app_root


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = r"Local\vrctool-single-instance"
INSTANCE_FILE = "vrctool.instance.json"


class SingleInstanceGuard:
    def __init__(self) -> None:
        self._mutex_handle: Optional[int] = None
        self._lock_file = None
        self._lock_path: Optional[Path] = None

    def acquire(self) -> bool:
        if os.name == "nt":
            return self._acquire_windows_mutex()
        return self._acquire_lock_file()

    def write_instance(self, host: str, port: int) -> None:
        info = {
            "pid": os.getpid(),
            "host": host,
            "port": int(port),
            "url": f"http://{host}:{int(port)}",
            "started_at": time.time(),
        }
        try:
            instance_path().write_text(
                json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def close(self) -> None:
        self._clear_instance_file()
        if self._mutex_handle is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex(self._mutex_handle)
            kernel32.CloseHandle(self._mutex_handle)
            self._mutex_handle = None
        if self._lock_file is not None:
            try:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            finally:
                self._lock_file = None

    def _acquire_windows_mutex(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._mutex_handle = handle
        return True

    def _acquire_lock_file(self) -> bool:
        self._lock_path = app_root() / "vrctool.lock"
        self._lock_file = self._lock_path.open("a+", encoding="utf-8")
        if os.name == "posix":
            import fcntl

            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
        return True

    def _clear_instance_file(self) -> None:
        path = instance_path()
        try:
            info = read_running_instance()
            if info and int(info.get("pid", -1)) != os.getpid():
                return
            path.unlink(missing_ok=True)
        except OSError:
            pass


def instance_path() -> Path:
    return app_root() / INSTANCE_FILE


def read_running_instance() -> Optional[Dict[str, Any]]:
    path = instance_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None
