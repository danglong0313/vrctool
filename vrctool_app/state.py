from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any, Deque, Dict

from vrctool_app import __version__


class RuntimeState:
    def __init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self._lock = RLock()
        self._logs: Deque[Dict[str, Any]] = deque(maxlen=300)
        self.data: Dict[str, Any] = {
            "app": {
                "name": "vrctool",
                "version": __version__,
                "started_at": now,
                "web_host": "127.0.0.1",
                "web_port": 8765,
                "configured_web_port": 8765,
                "port_temporary": False,
                "restart_required": False,
                "release_notes": {},
                "show_release_notes": True,
                "dismissed_release_notes_version": "",
            },
            "update": {
                "current_version": __version__,
                "latest_version": "",
                "status": "idle",
                "available": False,
                "can_install": False,
                "release_name": "",
                "release_notes": "",
                "release_url": "",
                "asset_name": "",
                "asset_size": 0,
                "download_url": "",
                "downloaded_bytes": 0,
                "progress": 0,
                "installer_path": "",
                "digest": "",
                "error": "",
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
                "batch_enabled": True,
                "batch_interval": 3.0,
                "batch_running": False,
                "batch_active_sources": [],
                "batch_order": [
                    "custom",
                    "device",
                    "afk",
                    "heart_rate",
                    "performance",
                    "now_playing",
                    "weather",
                    "dglab",
                ],
                "batch_current_source": "",
                "batch_next_source": "",
                "last_message": "",
                "last_source": "",
            },
            "device": {},
            "afk": {
                "start_time": now,
                "elapsed_seconds": 0,
            },
            "heart_rate": {
                "available": True,
                "scanning": False,
                "connecting": False,
                "connected": False,
                "send_enabled": False,
                "interval": 1.0,
                "address": "",
                "device_name": "",
                "devices": [],
                "bpm": 0,
                "last_seen": "",
                "status": "未连接",
                "error": "",
            },
            "performance": {
                "available": False,
                "collector": "",
                "vrchat_running": False,
                "process_id": 0,
                "sampling": False,
                "broadcast_enabled": False,
                "interval": 3.0,
                "low_fps_threshold": 45.0,
                "show_avg_fps": False,
                "show_frame_ms": True,
                "fps": 0.0,
                "avg_fps": 0.0,
                "frame_ms": 0.0,
                "low_fps": False,
                "active_swap_chain": "",
                "sample_count": 0,
                "needs_permission": False,
                "relogin_required": False,
                "status": "等待启动",
                "reason": "",
                "last_sample": "",
                "last_sent": "",
                "last_message": "",
            },
            "now_playing": {
                "available": False,
                "ready": False,
                "playing": False,
                "broadcast_enabled": False,
                "interval": 5.0,
                "preferred_player": "auto",
                "show_title": True,
                "show_artist": True,
                "show_album": False,
                "show_player": False,
                "show_progress": True,
                "source_id": "",
                "player": "",
                "player_name": "",
                "title": "",
                "artist": "",
                "album": "",
                "playback_status": "stopped",
                "position_seconds": 0.0,
                "duration_seconds": 0.0,
                "sessions": [],
                "status": "等待播放",
                "reason": "请先在 QQ 音乐、网易云音乐、汽水音乐或酷狗音乐中开始播放歌曲",
                "error": "",
                "last_update": "",
                "last_sent": "",
                "last_message": "",
            },
            "weather": {
                "available": True,
                "ready": False,
                "updating": False,
                "broadcast_enabled": False,
                "interval": 600.0,
                "latitude": None,
                "longitude": None,
                "location_name": "",
                "location_source": "",
                "location_accuracy": 0.0,
                "temperature": None,
                "feels_like": None,
                "humidity": None,
                "precipitation": None,
                "wind_speed": None,
                "weather_code": None,
                "condition": "",
                "timezone": "",
                "weather_time": "",
                "weather_provider": "",
                "status": "等待定位",
                "error": "",
                "last_update": "",
                "last_sent": "",
                "last_message": "",
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
                "channel_a": "A",
                "channel_b": "B",
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
