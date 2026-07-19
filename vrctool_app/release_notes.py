from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "v2.5.0 正在播放广播",
    "items": [
        "新增 QQ 音乐与网易云音乐的正在播放检测，并接入网页状态与 ChatBox 批量轮播。",
        "可分别开启歌名、歌手、专辑、播放器和播放进度，旧版消息模板会自动迁移为内容开关。",
        "ChatBox 消息固定以“正在播放:”开头，播放进度按歌曲比例移动并在第二行显示。",
        "QQ 音乐可以通过 Windows 媒体会话提供播放进度；网易云音乐官方客户端不支持返回有效进度时间轴，因此只显示歌曲信息。",
        "播放器暂停、退出或缺少有效歌曲信息时会自动退出轮播，恢复播放后自动重新加入。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
