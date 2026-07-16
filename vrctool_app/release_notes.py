from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "本次更新",
    "items": [
        "这是 v2.4.2 的后续稳定性补丁。",
        "天气广播现在会保留最新消息并持续加入 ChatBox 批量轮播。",
        "修复 DG-LAB 连接变化可能导致心跳任务退出、重连后断线越来越频繁的问题。",
        "DG-LAB 服务重启时会完整清理旧心跳任务，并提高短暂网络抖动的容忍度。",
        "郊狼 App 断线后会立即清理旧绑定、连接计数和强度状态，等待干净重连。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
