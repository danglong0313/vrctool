from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from vrctool_app import __version__


CURRENT_RELEASE_NOTES: Dict[str, Any] = {
    "version": __version__,
    "title": "本次更新",
    "items": [
        "新增命令行更新，可使用 vrctool upgrade 或 vrctool -u 完成检查、校验与安装。",
        "新增持久化网页端口，支持配置文件、命令行和网页基础设置弹窗修改。",
        "启动前检测网页端口占用，避免 OSC、DG-LAB 等组件进入半启动状态。",
        "新增按版本显示的更新内容弹窗，可选择同版本不再提醒。",
    ],
}


def current_release_notes() -> Dict[str, Any]:
    return deepcopy(CURRENT_RELEASE_NOTES)


def should_show_release_notes(current_version: str, dismissed_version: str) -> bool:
    return str(dismissed_version or "").strip() != str(current_version or "").strip()
