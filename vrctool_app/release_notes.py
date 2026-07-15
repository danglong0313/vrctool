from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "本次更新",
    "items": [
        "新增当前天气页面，显示温度、体感、湿度、风速和降水。",
        "支持浏览器自动定位、IP 估算回退和手动城市搜索。",
        "新增天气 ChatBox 定时广播，默认每 10 分钟更新一次。",
        "天气消息接入统一批量轮播，每次更新只发送一次，避免重复占用聊天框。",
        "天气广播开关和间隔会自动保存，重启 vrctool 后继续生效。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
