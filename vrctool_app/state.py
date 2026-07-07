from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any, Deque, Dict


class RuntimeState:
    def __init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self._lock = RLock()
        self._logs: Deque[Dict[str, Any]] = deque(maxlen=300)
        self.data: Dict[str, Any] = {
            "app": {
                "name": "VRC OSC 控制台",
                "started_at": now,
            },
            "chatbox": {
                "host": "127.0.0.1",
                "port": 9000,
                "device_enabled": False,
                "device_interval": 3.0,
                "afk_enabled": False,
                "afk_interval": 3.0,
                "custom_enabled": False,
                "custom_interval": 3.0,
                "custom_message": "",
                "dglab_enabled": False,
                "dglab_interval": 1.0,
                "last_message": "",
            },
            "device": {},
            "afk": {
                "start_time": now,
                "elapsed_seconds": 0,
            },
            "dglab": {
                "running": False,
                "bound": False,
                "listen_host": "0.0.0.0",
                "advertise_host": "",
                "port": 5678,
                "qr_text": "",
                "qr_image": "",
                "client_id": "",
                "target_id": "",
                "app_connections": 0,
                "strength_a": 0,
                "strength_b": 0,
                "limit_a": 100,
                "limit_b": 100,
                "safety_limit_a": 60,
                "safety_limit_b": 60,
                "mode_a": "interaction",
                "mode_b": "interaction",
                "selected_channel": "A",
                "panel_enabled": True,
                "panel_control": 1,
                "fire_step": 30,
                "adjust_step": 5,
                "fire_active": False,
                "waveform_a": "呼吸",
                "waveform_b": "呼吸",
                "pulse_enabled": True,
                "waveforms": [],
            },
            "osc": {
                "running": False,
                "listen_host": "127.0.0.1",
                "listen_port": 9001,
                "enabled": True,
                "address_a": "/avatar/parameters/DG-LAB/UpperLeg_L",
                "address_b": "/avatar/parameters/DG-LAB/UpperLeg_R",
                "threshold": 0.02,
                "custom_mappings": [],
                "last_address": "",
                "last_value": 0,
                "last_channel": "",
                "last_strength": 0,
            },
        }

    def log(self, level: str, message: str) -> None:
        with self._lock:
            self._logs.appendleft(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message,
                }
            )

    def patch(self, section: str, **values: Any) -> None:
        with self._lock:
            self.data[section].update(values)

    def patch_nested(self, section: str, key: str, **values: Any) -> None:
        with self._lock:
            self.data[section].setdefault(key, {}).update(values)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            result = deepcopy(self.data)
            result["logs"] = list(self._logs)
            return result
