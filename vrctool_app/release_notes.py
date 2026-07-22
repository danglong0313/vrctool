from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "v2.5.1 扩展音乐播放器适配",
    "items": [
        "正在播放检测新增汽水音乐与酷狗音乐，并支持自动选择或固定指定播放器。",
        "汽水音乐已验证可以通过 Windows 媒体会话返回歌曲信息与播放时间轴，ChatBox 第二行会显示动态进度。",
        "酷狗音乐兼容 KuGou、KuGoo、KGMusic 和中文媒体会话标识；能否显示进度取决于客户端版本是否公开时间轴。",
        "网易云音乐官方客户端仍不返回有效进度；本地数据库和界面渠道无法稳定取得实时位置，因此不会发送推算或虚假进度。",
        "网页状态、播放器选择、等待提示与 README 已同步更新为四播放器。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
