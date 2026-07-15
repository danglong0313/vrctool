from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "本次更新",
    "items": [
        "修复浏览器定位后错误显示“当前位置天气”的问题。",
        "当前位置会反向解析并显示真实城市名，城市解析结果会在本次运行中缓存。",
        "无法识别城市时不再显示占位地点，也不会发送不完整的天气消息。",
        "IP 定位和手动城市搜索同样只接受有效城市名，失败时会清空旧天气数据。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
