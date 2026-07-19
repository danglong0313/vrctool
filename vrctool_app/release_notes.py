from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "v2.4.4 补丁更新",
    "items": [
        "这是 v2.4.3 的后续稳定性补丁。",
        "ChatBox 批量轮播改为时间片模式，每个功能会在自己的时间片内按独立发送间隔持续更新。",
        "设备信息会在每次实际发送前重新采样，心率、帧率和郊狼状态会使用发送时的最新值。",
        "天气服务临时失败时保留上一次有效数据并继续轮播，后台异常不会终止后续更新。",
        "游戏帧率改用 PresentMon 事件时间统计，并排除失效交换链，减少延迟输出和多交换链造成的误差。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
