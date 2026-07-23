from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from vrctool_app.lyrics import LyricLine, LyricsResult
from vrctool_app.now_playing import (
    MediaSessionError,
    MediaSessionSnapshot,
    NowPlayingManager,
    detect_supported_player,
    format_now_playing_message,
    format_progress_line,
    select_session,
    timeline_progress_seconds,
)
from vrctool_app.state import RuntimeState


class FakeMediaProvider:
    def __init__(self, sessions=None, error: Exception | None = None) -> None:
        self.sessions = list(sessions or [])
        self.error = error

    async def get_sessions(self) -> list[MediaSessionSnapshot]:
        if self.error:
            raise self.error
        return list(self.sessions)


class FakeLyricsProvider:
    def __init__(self, result: LyricsResult | None = None) -> None:
        self.result = result or LyricsResult()
        self.calls = []

    async def fetch_synced_lyrics(self, title, artist, album, duration_seconds):
        self.calls.append((title, artist, album, duration_seconds))
        return self.result


def media_session(
    player: str,
    title: str,
    *,
    status: str = "playing",
    artist: str = "歌手",
    position_seconds: float = 10.0,
    duration_seconds: float = 60.0,
) -> MediaSessionSnapshot:
    source_ids = {
        "qqmusic": "QQMusic.exe",
        "netease": "cloudmusic.exe",
        "soda": "汽水音乐",
        "kugou": "KuGou.exe",
    }
    player_names = {
        "qqmusic": "QQ 音乐",
        "netease": "网易云音乐",
        "soda": "汽水音乐",
        "kugou": "酷狗音乐",
    }
    return MediaSessionSnapshot(
        source_id=source_ids[player],
        player=player,
        player_name=player_names[player],
        title=title,
        artist=artist,
        album="专辑",
        playback_status=status,
        position_seconds=position_seconds,
        duration_seconds=duration_seconds,
    )


class NowPlayingFormattingTests(unittest.TestCase):
    def test_supported_player_identifiers_cover_all_supported_players(self) -> None:
        self.assertEqual(detect_supported_player("QQMusic.exe"), "qqmusic")
        self.assertEqual(detect_supported_player("cloudmusic.exe"), "netease")
        self.assertEqual(detect_supported_player("Orpheus.MediaSession"), "netease")
        self.assertEqual(detect_supported_player("SodaMusic.exe"), "soda")
        self.assertEqual(detect_supported_player("汽水音乐"), "soda")
        self.assertEqual(detect_supported_player("KuGou.exe"), "kugou")
        self.assertEqual(detect_supported_player("KuGoo.exe"), "kugou")
        self.assertEqual(detect_supported_player("KGMusic.MediaSession"), "kugou")
        self.assertEqual(detect_supported_player("酷狗音乐"), "kugou")
        self.assertEqual(detect_supported_player("chrome.exe"), "")

    def test_auto_selection_prefers_playing_session_then_qq(self) -> None:
        sessions = [
            media_session("qqmusic", "QQ 暂停", status="paused"),
            media_session("netease", "网易云播放中"),
        ]
        self.assertEqual(select_session(sessions).title, "网易云播放中")

        sessions[0] = media_session("qqmusic", "QQ 播放中")
        self.assertEqual(select_session(sessions).player, "qqmusic")

    def test_manual_selection_uses_requested_player(self) -> None:
        sessions = [
            media_session("qqmusic", "QQ"),
            media_session("netease", "网易云"),
            media_session("soda", "汽水"),
            media_session("kugou", "酷狗"),
        ]
        self.assertEqual(select_session(sessions, "netease").title, "网易云")
        self.assertEqual(select_session(sessions, "soda").title, "汽水")
        self.assertEqual(select_session(sessions, "kugou").title, "酷狗")

    def test_selected_content_is_combined_and_cleans_line_breaks(self) -> None:
        message = format_now_playing_message(
            {
                "title": "歌曲\n名称",
                "artist": "歌手",
                "album": "专辑",
                "player_name": "QQ 音乐",
                "show_title": True,
                "show_artist": True,
                "show_album": True,
                "show_player": True,
                "show_progress": True,
                "position_seconds": 10,
                "duration_seconds": 60,
            }
        )
        self.assertEqual(
            message,
            "正在播放: ♪ 歌曲 名称 | 歌手: 歌手 | 专辑: 专辑 | 播放器: QQ 音乐\n"
            "0:10 ->----- 1:00",
        )
        self.assertLessEqual(len(message), 240)

    def test_missing_artist_does_not_leave_trailing_separator(self) -> None:
        self.assertEqual(
            format_now_playing_message(
                {
                    "title": "纯音乐",
                    "artist": "",
                    "show_title": True,
                    "show_artist": True,
                }
            ),
            "正在播放: ♪ 纯音乐",
        )

    def test_progress_line_matches_requested_chatbox_format(self) -> None:
        self.assertEqual(format_progress_line(10, 60), "0:10 ->----- 1:00")
        self.assertEqual(format_progress_line(30, 60), "0:30 --->--- 1:00")
        self.assertEqual(format_progress_line(60, 60), "1:00 ------> 1:00")

    def test_current_lyric_is_rendered_as_chatbox_third_line(self) -> None:
        message = format_now_playing_message(
            {
                "title": "测试歌曲",
                "artist": "测试歌手",
                "show_title": True,
                "show_artist": True,
                "show_progress": True,
                "show_lyrics": True,
                "position_seconds": 10,
                "duration_seconds": 60,
                "lyric": "这是当前歌词",
            }
        )

        self.assertEqual(
            message,
            "正在播放: ♪ 测试歌曲 | 歌手: 测试歌手\n"
            "0:10 ->----- 1:00\n"
            "歌词: 这是当前歌词",
        )
        self.assertLessEqual(len(message), 240)

    def test_timeline_position_advances_from_last_update_while_playing(self) -> None:
        now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        timeline = SimpleNamespace(
            start_time=timedelta(0),
            end_time=timedelta(seconds=60),
            position=timedelta(seconds=10),
            min_seek_time=timedelta(0),
            max_seek_time=timedelta(seconds=60),
            last_updated_time=now - timedelta(seconds=2.5),
        )

        position, duration = timeline_progress_seconds(
            timeline,
            "playing",
            1.0,
            now=now,
        )

        self.assertAlmostEqual(position, 12.5)
        self.assertEqual(duration, 60.0)


class NowPlayingManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_exposes_current_qq_music_session(self) -> None:
        state = RuntimeState()
        changes: list[bool] = []
        provider = FakeMediaProvider([media_session("qqmusic", "测试歌曲")])
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=provider,
            source_changed=lambda: changes.append(True),
        )

        self.assertTrue(await manager.refresh())
        current = state.snapshot()["now_playing"]
        self.assertTrue(current["available"])
        self.assertTrue(current["playing"])
        self.assertEqual(current["player"], "qqmusic")
        self.assertEqual(current["title"], "测试歌曲")
        self.assertEqual(current["position_seconds"], 10.0)
        self.assertEqual(current["duration_seconds"], 60.0)
        self.assertTrue(changes)

    async def test_refresh_failure_degrades_without_raising(self) -> None:
        state = RuntimeState()
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=FakeMediaProvider(error=MediaSessionError("媒体接口不可用")),
        )

        self.assertFalse(await manager.refresh())
        current = state.snapshot()["now_playing"]
        self.assertFalse(current["available"])
        self.assertEqual(current["status"], "检测不可用")
        self.assertIn("媒体接口不可用", current["error"])

    async def test_broadcast_sends_only_while_playing_and_cleans_tasks(self) -> None:
        state = RuntimeState()
        sent: list[str] = []
        provider = FakeMediaProvider([media_session("netease", "循环测试")])
        manager = NowPlayingManager(state, sent.append, provider=provider)

        await manager.start()
        await manager.configure(True, 1.0, "netease", True, True, False, False, True)
        for _ in range(20):
            if sent:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(
            sent[0],
            "正在播放: ♪ 循环测试 | 歌手: 歌手\n0:10 ->----- 1:00",
        )
        self.assertIsNotNone(manager._monitor_task)
        self.assertIsNotNone(manager._broadcast_task)

        provider.sessions = [media_session("netease", "循环测试", status="paused")]
        await manager.refresh()
        self.assertFalse(manager._send_current())
        await manager.shutdown()
        self.assertIsNone(manager._monitor_task)
        self.assertIsNone(manager._broadcast_task)

    async def test_invalid_player_selection_is_rejected(self) -> None:
        manager = NowPlayingManager(
            RuntimeState(),
            lambda _message: None,
            provider=FakeMediaProvider(),
        )
        with self.assertRaises(ValueError):
            await manager.configure(False, 5, "spotify", True, True, False, False, True)

    async def test_soda_and_kugou_player_selections_are_accepted(self) -> None:
        state = RuntimeState()
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=FakeMediaProvider(),
        )

        for player, label in (("soda", "汽水音乐"), ("kugou", "酷狗音乐")):
            await manager.configure(False, 5, player, True, True, False, False, True)
            current = state.snapshot()["now_playing"]
            self.assertEqual(current["preferred_player"], player)
            self.assertEqual(current["reason"], f"未检测到{label}的播放信息")

    async def test_at_least_one_content_switch_is_required(self) -> None:
        manager = NowPlayingManager(
            RuntimeState(),
            lambda _message: None,
            provider=FakeMediaProvider(),
        )
        with self.assertRaises(ValueError):
            await manager.configure(False, 5, "auto", False, False, False, False, False)

    async def test_lyrics_require_progress_to_keep_chatbox_third_line(self) -> None:
        manager = NowPlayingManager(
            RuntimeState(),
            lambda _message: None,
            provider=FakeMediaProvider(),
        )
        with self.assertRaisesRegex(ValueError, "同时开启播放进度"):
            await manager.configure(
                False,
                5,
                "auto",
                True,
                True,
                False,
                False,
                False,
                True,
            )

    async def test_synced_lyrics_follow_current_media_position(self) -> None:
        state = RuntimeState()
        media_provider = FakeMediaProvider(
            [media_session("qqmusic", "测试歌曲", position_seconds=12)]
        )
        lyrics_provider = FakeLyricsProvider(
            LyricsResult(
                lines=(
                    LyricLine(1.0, "第一句"),
                    LyricLine(10.0, "第二句"),
                ),
                matched=True,
            )
        )
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=media_provider,
            lyrics_provider=lyrics_provider,
        )

        await manager.configure(
            False,
            5,
            "auto",
            True,
            True,
            False,
            False,
            True,
            True,
        )
        self.assertIsNotNone(manager._lyrics_task)
        await manager._lyrics_task

        current = state.snapshot()["now_playing"]
        self.assertTrue(current["lyrics_ready"])
        self.assertEqual(current["lyric"], "第二句")
        self.assertEqual(len(lyrics_provider.calls), 1)

        media_provider.sessions = [
            media_session("qqmusic", "测试歌曲", position_seconds=2)
        ]
        await manager.refresh()
        self.assertEqual(state.snapshot()["now_playing"]["lyric"], "第一句")
        self.assertEqual(len(lyrics_provider.calls), 1)
        await manager.shutdown()

    async def test_forced_refresh_retries_a_cached_lyrics_miss(self) -> None:
        state = RuntimeState()
        media_provider = FakeMediaProvider(
            [media_session("qqmusic", "测试歌曲", position_seconds=12)]
        )
        lyrics_provider = FakeLyricsProvider(LyricsResult())
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=media_provider,
            lyrics_provider=lyrics_provider,
        )

        await manager.configure(
            False,
            5,
            "auto",
            True,
            True,
            False,
            False,
            True,
            True,
        )
        await manager._lyrics_task
        self.assertEqual(state.snapshot()["now_playing"]["lyrics_status"], "未找到同步歌词")

        lyrics_provider.result = LyricsResult(
            lines=(LyricLine(1.0, "重试找到的歌词"),),
            matched=True,
            source="QQ音乐歌词",
        )
        await manager.refresh(force_lyrics=True)
        await manager._lyrics_task

        current = state.snapshot()["now_playing"]
        self.assertEqual(current["lyric"], "重试找到的歌词")
        self.assertEqual(current["lyrics_source"], "QQ音乐歌词")
        self.assertEqual(len(lyrics_provider.calls), 2)
        await manager.shutdown()

    async def test_lyrics_are_not_requested_without_a_valid_timeline(self) -> None:
        state = RuntimeState()
        lyrics_provider = FakeLyricsProvider()
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=FakeMediaProvider(
                [
                    media_session(
                        "netease",
                        "无进度歌曲",
                        position_seconds=0,
                        duration_seconds=0,
                    )
                ]
            ),
            lyrics_provider=lyrics_provider,
        )

        await manager.configure(
            False,
            5,
            "netease",
            True,
            True,
            False,
            False,
            True,
            True,
        )

        self.assertFalse(lyrics_provider.calls)
        self.assertIn("无法同步歌词", state.snapshot()["now_playing"]["lyrics_status"])
        await manager.shutdown()

    async def test_kugou_does_not_request_unsupported_lyrics(self) -> None:
        state = RuntimeState()
        lyrics_provider = FakeLyricsProvider()
        manager = NowPlayingManager(
            state,
            lambda _message: None,
            provider=FakeMediaProvider(
                [media_session("kugou", "测试歌曲", duration_seconds=60)]
            ),
            lyrics_provider=lyrics_provider,
        )

        await manager.configure(
            False,
            5,
            "kugou",
            True,
            True,
            False,
            False,
            True,
            True,
        )

        self.assertFalse(lyrics_provider.calls)
        self.assertEqual(
            state.snapshot()["now_playing"]["lyrics_status"],
            "当前播放器暂不支持歌词",
        )
        await manager.shutdown()
