from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "v2.5.2 歌词显示更新",
    "items": [
        "QQ 音乐和汽水音乐现在支持显示歌词。",
        "歌词会跟着歌曲播放，并显示在 ChatBox 第三行。",
        "中文歌曲会优先显示简体歌词，减少出现繁体歌词的情况。",
        "网易云音乐和酷狗音乐暂不支持歌词。",
        "识别到不同音乐软件时，页面会显示对应的软件图标。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
