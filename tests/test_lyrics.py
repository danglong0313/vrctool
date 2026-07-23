from __future__ import annotations

import json
import unittest

from vrctool_app.lyrics import (
    LrcLibLyricsProvider,
    LyricsLookupError,
    LyricsResult,
    NeteaseLyricsProvider,
    OnlineLyricsProvider,
    QQLyricsProvider,
    current_lyric_line,
    parse_synced_lyrics,
)


class FakeResponse:
    def __init__(self, payload) -> None:
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self.payload


class LyricsFormattingTests(unittest.TestCase):
    def test_lrc_parser_supports_multiple_timestamps_and_translation_lines(self) -> None:
        lines = parse_synced_lyrics(
            "[ar:歌手]\n"
            "[00:01.50][00:05.00]<00:01.50>第一句\n"
            "[00:05.00]First line\n"
            "[00:09.250]第二句\n"
        )

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].timestamp_seconds, 1.5)
        self.assertEqual(lines[0].text, "第一句")
        self.assertEqual(lines[1].text, "第一句 / First line")
        self.assertEqual(lines[2].timestamp_seconds, 9.25)

    def test_current_line_follows_playback_position(self) -> None:
        lines = parse_synced_lyrics("[00:02.00]第一句\n[00:06.00]第二句")

        self.assertEqual(current_lyric_line(lines, 1.0), "")
        self.assertEqual(current_lyric_line(lines, 2.0), "第一句")
        self.assertEqual(current_lyric_line(lines, 8.0), "第二句")


class LrcLibProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_identifies_client_and_parses_synced_result(self) -> None:
        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                {
                    "trackName": "测试歌曲",
                    "artistName": "测试歌手",
                    "albumName": "测试专辑",
                    "duration": 60,
                    "instrumental": False,
                    "syncedLyrics": "[00:01.00]第一句\n[00:04.00]第二句",
                }
            )

        provider = LrcLibLyricsProvider(opener=opener, timeout=3)
        result = await provider.fetch_synced_lyrics(
            "测试歌曲",
            "测试歌手",
            "测试专辑",
            60,
        )

        self.assertTrue(result.matched)
        self.assertEqual([line.text for line in result.lines], ["第一句", "第二句"])
        self.assertEqual(requests[0][1], 3)
        self.assertIn("vrctool/", requests[0][0].get_header("User-agent"))
        self.assertIn("/api/get?", requests[0][0].full_url)

    async def test_search_fallback_selects_timed_and_duration_matched_record(self) -> None:
        def opener(_request, *, timeout):
            self.assertEqual(timeout, 8.0)
            return FakeResponse(
                [
                    {
                        "trackName": "测试歌曲",
                        "artistName": "其他歌手",
                        "duration": 200,
                        "syncedLyrics": "[00:01.00]错误匹配",
                    },
                    {
                        "trackName": "测试歌曲",
                        "artistName": "测试歌手",
                        "duration": 60,
                        "syncedLyrics": "[00:01.00]正确匹配",
                    },
                ]
            )

        result = await LrcLibLyricsProvider(opener=opener).fetch_synced_lyrics(
            "测试歌曲",
            "测试歌手",
            "",
            60,
        )

        self.assertEqual(result.lines[0].text, "正确匹配")

    async def test_search_retries_without_artist_and_with_simplified_title(self) -> None:
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if "artist_name=" in request.full_url:
                return FakeResponse([])
            return FakeResponse(
                [
                    {
                        "trackName": "测试歌曲",
                        "artistName": "歌词库中的另一种歌手写法",
                        "duration": 60,
                        "syncedLyrics": "[00:01.00]宽松匹配成功",
                    }
                ]
            )

        result = await LrcLibLyricsProvider(opener=opener).fetch_synced_lyrics(
            "测试歌曲（现场版）",
            "测试歌手 / 合唱歌手",
            "",
            60,
        )

        self.assertEqual(result.lines[0].text, "宽松匹配成功")
        self.assertTrue(any("track_name=" in url and "artist_name=" not in url for url in requested_urls))


class NeteaseProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_searches_song_and_merges_translated_lyrics(self) -> None:
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if "/api/search/get/web?" in request.full_url:
                return FakeResponse(
                    {
                        "code": 200,
                        "result": {
                            "songs": [
                                {
                                    "id": 100,
                                    "name": "测试歌曲",
                                    "artists": [{"name": "其他歌手"}],
                                    "album": {"name": "其他专辑"},
                                    "duration": 180000,
                                },
                                {
                                    "id": 200,
                                    "name": "测试歌曲",
                                    "artists": [{"name": "测试歌手"}],
                                    "album": {"name": "测试专辑"},
                                    "duration": 60000,
                                },
                            ]
                        },
                    }
                )
            return FakeResponse(
                {
                    "code": 200,
                    "lrc": {"lyric": "[00:01.00]第一句\n[00:05.00]第二句"},
                    "tlyric": {"lyric": "[00:01.00]First line"},
                }
            )

        result = await NeteaseLyricsProvider(opener=opener).fetch_synced_lyrics(
            "测试歌曲",
            "测试歌手",
            "测试专辑",
            60,
        )

        self.assertEqual(result.source, "网易云歌词")
        self.assertEqual(result.lines[0].text, "第一句 / First line")
        self.assertIn("id=200", requested_urls[-1])


class QQProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_selects_exact_song_and_decodes_lyrics(self) -> None:
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if "/client_search_cp?" in request.full_url:
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "song": {
                                "list": [
                                    {
                                        "songmid": "wrong",
                                        "songname": "测试歌曲",
                                        "singer": [{"name": "其他歌手"}],
                                        "albumname": "其他专辑",
                                        "interval": 180,
                                    },
                                    {
                                        "songmid": "correct",
                                        "songname": "测试歌曲",
                                        "singer": [{"name": "测试歌手"}],
                                        "albumname": "测试专辑",
                                        "interval": 60,
                                    },
                                ]
                            }
                        },
                    }
                )
            return FakeResponse(
                {
                    "code": 0,
                    "lyric": "[00&#58;01.00]第一句\n[00&#58;05.00]第二句",
                    "trans": "[00&#58;01.00]First line",
                }
            )

        result = await QQLyricsProvider(opener=opener).fetch_synced_lyrics(
            "测试歌曲",
            "测试歌手",
            "测试专辑",
            60,
        )

        self.assertEqual(result.source, "QQ音乐歌词")
        self.assertEqual(result.lines[0].text, "第一句 / First line")
        self.assertIn("songmid=correct", requested_urls[-1])


class OnlineProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_chinese_tracks_prefer_qq_music_while_other_tracks_prefer_lrclib(self) -> None:
        provider = OnlineLyricsProvider()

        self.assertIsInstance(provider._cjk_providers[0], QQLyricsProvider)
        self.assertIsInstance(provider._default_providers[0], LrcLibLyricsProvider)

    async def test_falls_back_when_lrclib_has_no_synced_lyrics(self) -> None:
        class FakeProvider:
            def __init__(self, result):
                self.result = result
                self.calls = 0

            async def fetch_synced_lyrics(self, *_args):
                self.calls += 1
                if isinstance(self.result, Exception):
                    raise self.result
                return self.result

        lrclib = FakeProvider(LyricsResult(matched=True, source="LRCLIB"))
        netease = FakeProvider(
            LyricsResult(
                lines=parse_synced_lyrics("[00:01.00]备用歌词"),
                matched=True,
                source="网易云歌词",
            )
        )
        provider = OnlineLyricsProvider((lrclib, netease))

        result = await provider.fetch_synced_lyrics("歌名", "歌手", "", 60)

        self.assertEqual(result.lines[0].text, "备用歌词")
        self.assertEqual(result.source, "网易云歌词")
        self.assertEqual(lrclib.calls, 1)
        self.assertEqual(netease.calls, 1)

    async def test_reports_failure_only_when_all_sources_fail(self) -> None:
        class FailedProvider:
            async def fetch_synced_lyrics(self, *_args):
                raise LyricsLookupError("连接失败")

        provider = OnlineLyricsProvider((FailedProvider(), FailedProvider()))

        with self.assertRaisesRegex(LyricsLookupError, "连接失败"):
            await provider.fetch_synced_lyrics("歌名", "歌手", "", 60)


if __name__ == "__main__":
    unittest.main()
