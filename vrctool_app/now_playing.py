from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from vrctool_app.state import RuntimeState

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )
except (ImportError, OSError):
    GlobalSystemMediaTransportControlsSessionManager = None
    GlobalSystemMediaTransportControlsSessionPlaybackStatus = None


DEFAULT_INTERVAL = 5.0
MIN_INTERVAL = 1.0
MAX_INTERVAL = 60.0
POLL_INTERVAL = 1.0
PROGRESS_SEGMENTS = 6
MAX_MESSAGE_LENGTH = 240
SUPPORTED_PLAYERS = ("auto", "qqmusic", "netease", "soda", "kugou")
PLAYER_LABELS = {
    "auto": "自动选择",
    "qqmusic": "QQ 音乐",
    "netease": "网易云音乐",
    "soda": "汽水音乐",
    "kugou": "酷狗音乐",
}
PLAYER_IDENTIFIERS = {
    "qqmusic": ("qqmusic", "qq music", "qq音乐"),
    "netease": ("cloudmusic", "netease", "orpheus", "网易云"),
    "soda": ("sodamusic", "soda music", "qishui", "汽水音乐"),
    "kugou": ("kugou", "kugoo", "ku gou", "kgmusic", "酷狗音乐", "酷狗"),
}


class MediaSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaSessionSnapshot:
    source_id: str
    player: str
    player_name: str
    title: str
    artist: str = ""
    album: str = ""
    playback_status: str = "unknown"
    position_seconds: float = 0.0
    duration_seconds: float = 0.0

    @property
    def playing(self) -> bool:
        return self.playback_status == "playing"


class MediaSessionProvider(Protocol):
    async def get_sessions(self) -> list[MediaSessionSnapshot]: ...


def detect_supported_player(source_id: str) -> str:
    normalized = str(source_id or "").casefold()
    for player, identifiers in PLAYER_IDENTIFIERS.items():
        if any(identifier.casefold() in normalized for identifier in identifiers):
            return player
    return ""


def normalize_playback_status(value: Any) -> str:
    name = str(getattr(value, "name", value) or "").casefold()
    for status in ("playing", "paused", "stopped", "closed", "opened", "changing"):
        if status in name:
            return status
    return "unknown"


def clean_media_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", "").split()).strip()


def format_playback_time(seconds: Any) -> str:
    try:
        total_seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def format_progress_line(position_seconds: Any, duration_seconds: Any) -> str:
    try:
        duration = float(duration_seconds)
        position = float(position_seconds)
    except (TypeError, ValueError):
        return ""
    if duration <= 0:
        return ""
    position = max(0.0, min(position, duration))
    marker = min(PROGRESS_SEGMENTS, int((position / duration) * PROGRESS_SEGMENTS))
    progress_bar = "-" * marker + ">" + "-" * (PROGRESS_SEGMENTS - marker)
    return (
        f"{format_playback_time(position)} {progress_bar} "
        f"{format_playback_time(duration)}"
    )


def timeline_progress_seconds(
    timeline: Any,
    playback_status: str,
    playback_rate: Any = None,
    *,
    now: Optional[datetime] = None,
) -> tuple[float, float]:
    def timespan_seconds(value: Any) -> float:
        try:
            return float(value.total_seconds())
        except (AttributeError, TypeError, ValueError):
            return 0.0

    start = timespan_seconds(getattr(timeline, "start_time", None))
    end = timespan_seconds(getattr(timeline, "end_time", None))
    position = timespan_seconds(getattr(timeline, "position", None))
    duration = end - start
    position -= start
    if duration <= 0:
        minimum = timespan_seconds(getattr(timeline, "min_seek_time", None))
        maximum = timespan_seconds(getattr(timeline, "max_seek_time", None))
        duration = maximum - minimum
        position = timespan_seconds(getattr(timeline, "position", None)) - minimum
    if duration <= 0:
        return 0.0, 0.0

    updated_at = getattr(timeline, "last_updated_time", None)
    if playback_status == "playing" and isinstance(updated_at, datetime) and updated_at.year >= 2000:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        elapsed = (current_time.astimezone(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()
        try:
            rate = float(playback_rate) if playback_rate is not None else 1.0
        except (TypeError, ValueError):
            rate = 1.0
        if 0.0 <= elapsed <= 86400.0:
            position += elapsed * max(0.0, rate)
    return max(0.0, min(position, duration)), duration


def format_now_playing_message(now_playing: dict[str, Any]) -> str:
    title = clean_media_text(now_playing.get("title"))
    if not title:
        return ""
    artist = clean_media_text(now_playing.get("artist"))
    album = clean_media_text(now_playing.get("album"))
    player = clean_media_text(now_playing.get("player_name"))
    parts: list[str] = []
    if now_playing.get("show_title", True):
        parts.append(f"♪ {title}")
    if now_playing.get("show_artist", True) and artist:
        parts.append(f"歌手: {artist}")
    if now_playing.get("show_album") and album:
        parts.append(f"专辑: {album}")
    if now_playing.get("show_player") and player:
        parts.append(f"播放器: {player}")
    progress_line = ""
    if now_playing.get("show_progress", True):
        progress_line = format_progress_line(
            now_playing.get("position_seconds"),
            now_playing.get("duration_seconds"),
        )
    if not parts and not progress_line:
        return ""
    first_line = f"正在播放: {' | '.join(parts)}" if parts else "正在播放:"
    if not progress_line:
        return first_line[:MAX_MESSAGE_LENGTH]
    first_line_limit = max(0, MAX_MESSAGE_LENGTH - len(progress_line) - 1)
    return f"{first_line[:first_line_limit]}\n{progress_line}"


def select_session(
    sessions: Iterable[MediaSessionSnapshot],
    preferred_player: str = "auto",
) -> Optional[MediaSessionSnapshot]:
    supported = [session for session in sessions if session.player in PLAYER_LABELS and session.player != "auto"]
    if preferred_player in PLAYER_LABELS and preferred_player != "auto":
        supported = [session for session in supported if session.player == preferred_player]
    if not supported:
        return None
    priority = {player: index for index, player in enumerate(SUPPORTED_PLAYERS[1:])}
    return min(
        supported,
        key=lambda session: (
            not bool(session.title),
            not session.playing,
            priority.get(session.player, 99),
            session.source_id.casefold(),
        ),
    )


class WinRTMediaSessionProvider:
    def __init__(self) -> None:
        self._manager: Any = None

    async def get_sessions(self) -> list[MediaSessionSnapshot]:
        if GlobalSystemMediaTransportControlsSessionManager is None:
            raise MediaSessionError("缺少 Windows 媒体会话组件，请重新安装或更新 vrctool")
        try:
            if self._manager is None:
                self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            raw_sessions = list(self._manager.get_sessions())
        except Exception as exc:
            self._manager = None
            raise MediaSessionError(f"无法读取 Windows 媒体会话：{exc}") from exc

        sessions: list[MediaSessionSnapshot] = []
        for session in raw_sessions:
            try:
                source_id = clean_media_text(session.source_app_user_model_id)
                player = detect_supported_player(source_id)
                if not player:
                    continue
                properties = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                playback_status = normalize_playback_status(playback.playback_status)
                position_seconds = 0.0
                duration_seconds = 0.0
                try:
                    timeline = session.get_timeline_properties()
                    position_seconds, duration_seconds = timeline_progress_seconds(
                        timeline,
                        playback_status,
                        getattr(playback, "playback_rate", None),
                    )
                except Exception:
                    pass
                sessions.append(
                    MediaSessionSnapshot(
                        source_id=source_id,
                        player=player,
                        player_name=PLAYER_LABELS[player],
                        title=clean_media_text(properties.title),
                        artist=clean_media_text(properties.artist),
                        album=clean_media_text(properties.album_title),
                        playback_status=playback_status,
                        position_seconds=position_seconds,
                        duration_seconds=duration_seconds,
                    )
                )
            except Exception:
                continue
        return sessions


class NowPlayingManager:
    def __init__(
        self,
        state: RuntimeState,
        send_message: Callable[[str], Any],
        *,
        provider: Optional[MediaSessionProvider] = None,
        source_changed: Optional[Callable[[], Any]] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.state = state
        self.send_message = send_message
        self._provider = provider or WinRTMediaSessionProvider()
        self._source_changed = source_changed or (lambda: None)
        self._sleep = sleep
        self._monitor_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        self._broadcast_wakeup = asyncio.Event()

    async def start(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            return
        await self.refresh()
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(),
            name="vrctool-now-playing-monitor",
        )
        if self.state.snapshot()["now_playing"].get("broadcast_enabled"):
            self._ensure_broadcast_task()

    async def configure(
        self,
        enabled: bool,
        interval: float,
        preferred_player: str,
        show_title: bool,
        show_artist: bool,
        show_album: bool,
        show_player: bool,
        show_progress: bool,
    ) -> None:
        preferred_player = str(preferred_player or "auto").casefold()
        if preferred_player not in SUPPORTED_PLAYERS:
            choices = "、".join(PLAYER_LABELS[player] for player in SUPPORTED_PLAYERS)
            raise ValueError(f"播放器只能选择：{choices}")
        content_flags = (show_title, show_artist, show_album, show_player, show_progress)
        if not any(content_flags):
            raise ValueError("请至少开启一项 ChatBox 广播内容")
        interval = max(MIN_INTERVAL, min(float(interval), MAX_INTERVAL))
        self.state.patch(
            "now_playing",
            broadcast_enabled=bool(enabled),
            interval=interval,
            preferred_player=preferred_player,
            show_title=bool(show_title),
            show_artist=bool(show_artist),
            show_album=bool(show_album),
            show_player=bool(show_player),
            show_progress=bool(show_progress),
        )
        await self.refresh()
        await self._stop_broadcast_task()
        if enabled:
            self._ensure_broadcast_task()
            self._broadcast_wakeup.set()
            self.state.log("ok", f"正在播放 ChatBox 广播已开启，每 {interval:g} 秒发送一次")
        else:
            self.state.log("ok", "正在播放 ChatBox 广播已关闭")
        self._source_changed()

    async def refresh(self) -> bool:
        previous = self.state.snapshot()["now_playing"]
        previous_key = self._state_key(previous)
        try:
            sessions = await self._provider.get_sessions()
            preferred = str(previous.get("preferred_player") or "auto")
            selected = select_session(sessions, preferred)
            updates: dict[str, Any] = {
                "available": True,
                "error": "",
                "sessions": [asdict(session) for session in sessions],
                "last_update": datetime.now().strftime("%H:%M:%S"),
            }
            if selected is None:
                updates.update(
                    ready=False,
                    playing=False,
                    source_id="",
                    player="",
                    player_name="",
                    title="",
                    artist="",
                    album="",
                    playback_status="stopped",
                    position_seconds=0.0,
                    duration_seconds=0.0,
                    status="等待播放",
                    reason=self._empty_reason(sessions, preferred),
                    last_message="",
                )
            else:
                updates.update(
                    ready=bool(selected.title),
                    playing=selected.playing and bool(selected.title),
                    source_id=selected.source_id,
                    player=selected.player,
                    player_name=selected.player_name,
                    title=selected.title,
                    artist=selected.artist,
                    album=selected.album,
                    playback_status=selected.playback_status,
                    position_seconds=selected.position_seconds,
                    duration_seconds=selected.duration_seconds,
                    status="正在播放" if selected.playing else "已暂停",
                    reason=(
                        f"已连接 {selected.player_name} 的 Windows 媒体会话"
                        if selected.title
                        else f"{selected.player_name} 暂未提供歌曲信息"
                    ),
                )
            self.state.patch("now_playing", **updates)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.patch(
                "now_playing",
                available=False,
                ready=False,
                playing=False,
                position_seconds=0.0,
                duration_seconds=0.0,
                status="检测不可用",
                reason=str(exc),
                error=str(exc),
                sessions=[],
            )
            self.state.log("warn", f"正在播放检测失败：{exc}")
            self._notify_if_changed(previous_key)
            return False

        self._notify_if_changed(previous_key)
        return True

    async def shutdown(self) -> None:
        await self._stop_task("_monitor_task")
        await self._stop_broadcast_task()

    def _notify_if_changed(self, previous_key: tuple[Any, ...]) -> None:
        current = self.state.snapshot()["now_playing"]
        if self._state_key(current) == previous_key:
            return
        self._source_changed()
        if current.get("playing") and current.get("broadcast_enabled"):
            self._broadcast_wakeup.set()

    @staticmethod
    def _state_key(values: dict[str, Any]) -> tuple[Any, ...]:
        return (
            values.get("available"),
            values.get("playing"),
            values.get("player"),
            values.get("title"),
            values.get("artist"),
            values.get("album"),
        )

    @staticmethod
    def _empty_reason(sessions: list[MediaSessionSnapshot], preferred: str) -> str:
        if preferred in PLAYER_LABELS and preferred != "auto":
            return f"未检测到{PLAYER_LABELS[preferred]}的播放信息"
        if sessions:
            return "受支持的音乐播放器当前均未播放"
        return "请先在 QQ 音乐、网易云音乐、汽水音乐或酷狗音乐中开始播放歌曲"

    async def _monitor_loop(self) -> None:
        while True:
            await self._sleep(POLL_INTERVAL)
            await self.refresh()

    def _ensure_broadcast_task(self) -> None:
        if self._broadcast_task and not self._broadcast_task.done():
            return
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(),
            name="vrctool-now-playing-chatbox",
        )

    async def _stop_broadcast_task(self) -> None:
        await self._stop_task("_broadcast_task")

    async def _stop_task(self, attribute: str) -> None:
        task = getattr(self, attribute)
        setattr(self, attribute, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _broadcast_loop(self) -> None:
        while self.state.snapshot()["now_playing"].get("broadcast_enabled"):
            self._send_current()
            snapshot = self.state.snapshot()["now_playing"]
            try:
                interval = float(snapshot.get("interval") or DEFAULT_INTERVAL)
            except (TypeError, ValueError):
                interval = DEFAULT_INTERVAL
            interval = max(MIN_INTERVAL, min(interval, MAX_INTERVAL))
            self._broadcast_wakeup.clear()
            try:
                await asyncio.wait_for(self._broadcast_wakeup.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def _send_current(self) -> bool:
        snapshot = self.state.snapshot()["now_playing"]
        if not (
            snapshot.get("broadcast_enabled")
            and snapshot.get("playing")
            and snapshot.get("title")
        ):
            return False
        message = format_now_playing_message(snapshot)
        if not message:
            return False
        self.send_message(message)
        self.state.patch("now_playing", last_message=message)
        return True
