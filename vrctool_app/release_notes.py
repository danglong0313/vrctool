from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "本次更新",
    "items": [
        "这是 v2.4.1 的后续补丁，修复国内网络访问天气服务时可能返回 403 的问题。",
        "Open-Meteo 不可用时会自动切换 UAPI 国内备用天气源。",
        "国内 IP 定位与行政区解析优先使用国内接口，失败后仍会继续回退。",
        "地点显示补全为地级市与区县，例如“北京市朝阳区”。",
        "启动时会等待网页服务完全就绪后再打开浏览器，避免出现拒绝连接页面。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
