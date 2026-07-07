from __future__ import annotations

from threading import RLock
from typing import Callable, Optional

_lock = RLock()
_shutdown_callback: Optional[Callable[[], None]] = None


def set_shutdown_callback(callback: Optional[Callable[[], None]]) -> None:
    global _shutdown_callback
    with _lock:
        _shutdown_callback = callback


def request_shutdown() -> bool:
    with _lock:
        callback = _shutdown_callback
    if callback is None:
        return False
    callback()
    return True
