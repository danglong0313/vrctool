from __future__ import annotations

import asyncio
import html
import json
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vrctool_app import __version__


LRCLIB_API_BASE = "https://lrclib.net/api"
QQ_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
NETEASE_SEARCH_URL = "https://music.163.com/api/search/get/web"
NETEASE_LYRIC_URL = "https://music.163.com/api/song/lyric"
PROJECT_URL = "https://github.com/danglong0313/vrctool"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 8.0
_TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[\.:](\d{1,3}))?\]")
_INLINE_TIMESTAMP_RE = re.compile(r"<\d{1,3}:\d{2}(?:[\.:]\d{1,3})?>")
_TITLE_SUFFIX_RE = re.compile(r"\s*[\(\[（【][^\)\]）】]*[\)\]）】]\s*$")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class LyricsLookupError(RuntimeError):
    pass


@dataclass(frozen=True)
class LyricLine:
    timestamp_seconds: float
    text: str


@dataclass(frozen=True)
class LyricsResult:
    lines: tuple[LyricLine, ...] = ()
    matched: bool = False
    instrumental: bool = False
    source: str = "LRCLIB"


class LyricsProvider(Protocol):
    async def fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult: ...


def clean_lyric_text(value: Any) -> str:
    text = _INLINE_TIMESTAMP_RE.sub("", str(value or ""))
    return " ".join(text.replace("\x00", "").split()).strip()


def parse_synced_lyrics(value: Any) -> tuple[LyricLine, ...]:
    grouped: dict[float, list[str]] = {}
    for raw_line in str(value or "").splitlines():
        matches = list(_TIMESTAMP_RE.finditer(raw_line))
        if not matches:
            continue
        lyric_text = clean_lyric_text(_TIMESTAMP_RE.sub("", raw_line))
        if not lyric_text:
            continue
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction_text = match.group(3) or ""
            fraction = int(fraction_text) / (10 ** len(fraction_text)) if fraction_text else 0.0
            timestamp = round(minutes * 60 + seconds + fraction, 3)
            texts = grouped.setdefault(timestamp, [])
            if lyric_text not in texts:
                texts.append(lyric_text)

    return tuple(
        LyricLine(timestamp, " / ".join(grouped[timestamp]))
        for timestamp in sorted(grouped)
    )


def current_lyric_line(lines: tuple[LyricLine, ...], position_seconds: Any) -> str:
    try:
        position = max(0.0, float(position_seconds))
    except (TypeError, ValueError):
        return ""
    if not lines:
        return ""
    index = bisect_right(
        [line.timestamp_seconds for line in lines],
        position + 0.05,
    ) - 1
    return lines[index].text if index >= 0 else ""


def _identity(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").casefold()
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def _simplify_title(value: str) -> str:
    simplified = str(value or "").strip()
    while True:
        candidate = _TITLE_SUFFIX_RE.sub("", simplified).strip()
        if not candidate or candidate == simplified:
            break
        simplified = candidate
    return simplified or str(value or "").strip()


def _title_variants(value: str) -> tuple[str, ...]:
    variants: list[str] = []
    for candidate in (clean_lyric_text(value), _simplify_title(value)):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return tuple(variants)


def _contains_cjk(*values: Any) -> bool:
    return any(_CJK_RE.search(str(value or "")) for value in values)


class LrcLibLyricsProvider:
    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener
        self._timeout = max(1.0, float(timeout))
        self._user_agent = f"vrctool/{__version__} ({PROJECT_URL})"

    async def fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        return await asyncio.to_thread(
            self._fetch_synced_lyrics,
            title,
            artist,
            album,
            duration_seconds,
        )

    def _fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        title = clean_lyric_text(title)
        artist = clean_lyric_text(artist)
        album = clean_lyric_text(album)
        try:
            duration = max(0.0, float(duration_seconds))
        except (TypeError, ValueError):
            duration = 0.0
        if not title:
            return LyricsResult()

        if artist and album and duration > 0:
            record = self._request_json(
                "/get",
                {
                    "track_name": title,
                    "artist_name": artist,
                    "album_name": album,
                    "duration": round(duration),
                },
                not_found=None,
            )
            if isinstance(record, dict):
                return self._record_result(record)

        search_parameters: list[dict[str, str]] = []
        for query_title in _title_variants(title):
            if artist:
                search_parameters.append(
                    {"track_name": query_title, "artist_name": artist}
                )
            search_parameters.append({"track_name": query_title})
            if artist:
                search_parameters.append({"q": f"{query_title} {artist}"})

        unique_searches: list[dict[str, str]] = []
        seen_searches: set[tuple[tuple[str, str], ...]] = set()
        for parameters in search_parameters:
            signature = tuple(sorted(parameters.items()))
            if signature not in seen_searches:
                seen_searches.add(signature)
                unique_searches.append(parameters)

        for parameters in unique_searches:
            records = self._request_json(
                "/search",
                parameters,
                not_found=[],
            )
            record = self._select_record(records, title, artist, album, duration)
            if record is not None:
                return self._record_result(record)
        return LyricsResult()

    def _request_json(
        self,
        path: str,
        parameters: dict[str, Any],
        *,
        not_found: Any,
    ) -> Any:
        filtered = {
            key: value
            for key, value in parameters.items()
            if value is not None and str(value) != ""
        }
        url = f"{LRCLIB_API_BASE}{path}?{urlencode(filtered)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                return not_found
            raise LyricsLookupError(f"歌词服务返回 HTTP {exc.code}") from exc
        except (OSError, URLError) as exc:
            raise LyricsLookupError(f"无法连接歌词服务：{exc}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise LyricsLookupError("歌词服务响应过大")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LyricsLookupError("歌词服务返回了无效数据") from exc

    @staticmethod
    def _record_result(record: dict[str, Any]) -> LyricsResult:
        return LyricsResult(
            lines=parse_synced_lyrics(record.get("syncedLyrics")),
            matched=True,
            instrumental=bool(record.get("instrumental")),
        )

    @staticmethod
    def _select_record(
        records: Any,
        title: str,
        artist: str,
        album: str,
        duration: float,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(records, list):
            return None
        title_key = _identity(title)
        simplified_title_key = _identity(_simplify_title(title))
        artist_key = _identity(artist)
        album_key = _identity(album)

        def score(record: dict[str, Any]) -> float:
            record_title = _identity(record.get("trackName"))
            record_artist = _identity(record.get("artistName"))
            record_album = _identity(record.get("albumName"))
            total = 0.0
            if record_title == title_key:
                total += 120.0
            elif record_title == simplified_title_key:
                total += 105.0
            elif record_title and (
                record_title in title_key or simplified_title_key in record_title
            ):
                total += 55.0
            if artist_key and record_artist == artist_key:
                total += 60.0
            elif artist_key and record_artist and (
                artist_key in record_artist or record_artist in artist_key
            ):
                total += 28.0
            if album_key and record_album == album_key:
                total += 15.0
            try:
                difference = abs(float(record.get("duration") or 0.0) - duration)
            except (TypeError, ValueError):
                difference = 9999.0
            if duration > 0 and difference <= 2.0:
                total += 50.0
            elif duration > 0 and difference <= 5.0:
                total += 30.0
            elif duration > 0 and difference <= 10.0:
                total += 10.0
            if record.get("syncedLyrics"):
                total += 20.0
            return total

        candidates = [record for record in records if isinstance(record, dict)]
        if not candidates:
            return None
        selected = max(candidates, key=score)
        return selected if score(selected) >= 75.0 else None


class NeteaseLyricsProvider:
    """Search NetEase's public web catalogue as a Chinese-lyrics fallback."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener
        self._timeout = max(1.0, float(timeout))

    async def fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        return await asyncio.to_thread(
            self._fetch_synced_lyrics,
            title,
            artist,
            album,
            duration_seconds,
        )

    def _fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        title = clean_lyric_text(title)
        artist = clean_lyric_text(artist)
        album = clean_lyric_text(album)
        try:
            duration = max(0.0, float(duration_seconds))
        except (TypeError, ValueError):
            duration = 0.0
        if not title:
            return LyricsResult(source="网易云歌词")

        keywords: list[str] = []
        for query_title in _title_variants(title):
            for keyword in (
                f"{query_title} {artist}".strip(),
                query_title,
            ):
                if keyword and keyword not in keywords:
                    keywords.append(keyword)

        for keyword in keywords:
            payload = self._request_json(
                NETEASE_SEARCH_URL,
                {
                    "csrf_token": "",
                    "s": keyword,
                    "type": 1,
                    "offset": 0,
                    "total": "true",
                    "limit": 20,
                },
            )
            songs = payload.get("result", {}).get("songs", []) if isinstance(payload, dict) else []
            song = self._select_song(songs, title, artist, album, duration)
            if song is None:
                continue

            song_id = song.get("id")
            if song_id is None:
                continue
            lyrics_payload = self._request_json(
                NETEASE_LYRIC_URL,
                {"id": song_id, "lv": 1, "kv": 1, "tv": 1},
            )
            if not isinstance(lyrics_payload, dict):
                continue
            original = lyrics_payload.get("lrc", {}).get("lyric", "")
            translated = lyrics_payload.get("tlyric", {}).get("lyric", "")
            lines = parse_synced_lyrics(f"{original}\n{translated}")
            instrumental = bool(
                lyrics_payload.get("nolyric") or lyrics_payload.get("uncollected")
            )
            return LyricsResult(
                lines=lines,
                matched=True,
                instrumental=instrumental,
                source="网易云歌词",
            )

        return LyricsResult(source="网易云歌词")

    def _request_json(self, url: str, parameters: dict[str, Any]) -> Any:
        request = Request(
            f"{url}?{urlencode(parameters)}",
            headers={
                "Accept": "application/json",
                "Referer": "https://music.163.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    f"vrctool/{__version__}"
                ),
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise LyricsLookupError(f"网易云歌词接口返回 HTTP {exc.code}") from exc
        except (OSError, URLError) as exc:
            raise LyricsLookupError(f"无法连接网易云歌词接口：{exc}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise LyricsLookupError("网易云歌词接口响应过大")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LyricsLookupError("网易云歌词接口返回了无效数据") from exc

    @staticmethod
    def _select_song(
        songs: Any,
        title: str,
        artist: str,
        album: str,
        duration: float,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(songs, list):
            return None
        title_key = _identity(title)
        simplified_title_key = _identity(_simplify_title(title))
        artist_key = _identity(artist)
        album_key = _identity(album)

        def score(song: dict[str, Any]) -> float:
            song_title = _identity(song.get("name"))
            song_artists = _identity(
                " ".join(
                    str(item.get("name") or "")
                    for item in song.get("artists", [])
                    if isinstance(item, dict)
                )
            )
            song_album = _identity(
                (song.get("album") or {}).get("name")
                if isinstance(song.get("album"), dict)
                else ""
            )
            total = 0.0
            if song_title == title_key:
                total += 120.0
            elif song_title == simplified_title_key:
                total += 110.0
            elif song_title and (
                song_title in title_key or simplified_title_key in song_title
            ):
                total += 50.0
            if artist_key and song_artists == artist_key:
                total += 60.0
            elif artist_key and song_artists and (
                artist_key in song_artists or song_artists in artist_key
            ):
                total += 30.0
            if album_key and song_album == album_key:
                total += 15.0
            try:
                song_duration = float(song.get("duration") or song.get("dt") or 0.0)
                if song_duration > 10000:
                    song_duration /= 1000.0
                difference = abs(song_duration - duration)
            except (TypeError, ValueError):
                difference = 9999.0
            if duration > 0 and difference <= 2.0:
                total += 50.0
            elif duration > 0 and difference <= 5.0:
                total += 30.0
            elif duration > 0 and difference <= 10.0:
                total += 10.0
            return total

        candidates = [song for song in songs if isinstance(song, dict)]
        if not candidates:
            return None
        selected = max(candidates, key=score)
        return selected if score(selected) >= 90.0 else None


class QQLyricsProvider:
    """Use QQ Music's public web catalogue for Chinese synchronized lyrics."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener
        self._timeout = max(1.0, float(timeout))

    async def fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        return await asyncio.to_thread(
            self._fetch_synced_lyrics,
            title,
            artist,
            album,
            duration_seconds,
        )

    def _fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        title = clean_lyric_text(title)
        artist = clean_lyric_text(artist)
        album = clean_lyric_text(album)
        try:
            duration = max(0.0, float(duration_seconds))
        except (TypeError, ValueError):
            duration = 0.0
        if not title:
            return LyricsResult(source="QQ音乐歌词")

        keywords: list[str] = []
        for query_title in _title_variants(title):
            for keyword in (f"{query_title} {artist}".strip(), query_title):
                if keyword and keyword not in keywords:
                    keywords.append(keyword)

        for keyword in keywords:
            payload = self._request_json(
                QQ_SEARCH_URL,
                {"p": 1, "n": 20, "w": keyword, "format": "json"},
                referer="https://y.qq.com/",
            )
            songs = (
                payload.get("data", {}).get("song", {}).get("list", [])
                if isinstance(payload, dict)
                else []
            )
            song = self._select_song(songs, title, artist, album, duration)
            if song is None or not song.get("songmid"):
                continue
            lyrics_payload = self._request_json(
                QQ_LYRIC_URL,
                {
                    "songmid": song["songmid"],
                    "format": "json",
                    "nobase64": 1,
                    "g_tk": 5381,
                },
                referer="https://y.qq.com/portal/player.html",
            )
            if not isinstance(lyrics_payload, dict):
                continue
            original = html.unescape(str(lyrics_payload.get("lyric") or ""))
            translated = html.unescape(str(lyrics_payload.get("trans") or ""))
            lines = parse_synced_lyrics(f"{original}\n{translated}")
            return LyricsResult(
                lines=lines,
                matched=True,
                source="QQ音乐歌词",
            )

        return LyricsResult(source="QQ音乐歌词")

    def _request_json(
        self,
        url: str,
        parameters: dict[str, Any],
        *,
        referer: str,
    ) -> Any:
        request = Request(
            f"{url}?{urlencode(parameters)}",
            headers={
                "Accept": "application/json",
                "Referer": referer,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    f"vrctool/{__version__}"
                ),
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise LyricsLookupError(f"QQ音乐歌词接口返回 HTTP {exc.code}") from exc
        except (OSError, URLError) as exc:
            raise LyricsLookupError(f"无法连接 QQ 音乐歌词接口：{exc}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise LyricsLookupError("QQ音乐歌词接口响应过大")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LyricsLookupError("QQ音乐歌词接口返回了无效数据") from exc

    @staticmethod
    def _select_song(
        songs: Any,
        title: str,
        artist: str,
        album: str,
        duration: float,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(songs, list):
            return None
        title_key = _identity(title)
        simplified_title_key = _identity(_simplify_title(title))
        artist_key = _identity(artist)
        album_key = _identity(album)

        def score(song: dict[str, Any]) -> float:
            song_title = _identity(song.get("songname"))
            song_artists = _identity(
                " ".join(
                    str(item.get("name") or "")
                    for item in song.get("singer", [])
                    if isinstance(item, dict)
                )
            )
            song_album = _identity(song.get("albumname"))
            total = 0.0
            if song_title == title_key:
                total += 120.0
            elif song_title == simplified_title_key:
                total += 110.0
            elif song_title and (
                song_title in title_key or simplified_title_key in song_title
            ):
                total += 50.0
            if artist_key and song_artists == artist_key:
                total += 60.0
            elif artist_key and song_artists and (
                artist_key in song_artists or song_artists in artist_key
            ):
                total += 30.0
            if album_key and song_album == album_key:
                total += 15.0
            try:
                difference = abs(float(song.get("interval") or 0.0) - duration)
            except (TypeError, ValueError):
                difference = 9999.0
            if duration > 0 and difference <= 2.0:
                total += 50.0
            elif duration > 0 and difference <= 5.0:
                total += 30.0
            elif duration > 0 and difference <= 10.0:
                total += 10.0
            return total

        candidates = [song for song in songs if isinstance(song, dict)]
        if not candidates:
            return None
        selected = max(candidates, key=score)
        return selected if score(selected) >= 90.0 else None


class OnlineLyricsProvider:
    """Try multiple catalogues so the player brand does not limit coverage."""

    def __init__(self, providers: Optional[tuple[LyricsProvider, ...]] = None) -> None:
        if providers is not None:
            self._default_providers = providers
            self._cjk_providers = providers
            return
        lrclib = LrcLibLyricsProvider()
        qq_music = QQLyricsProvider()
        netease = NeteaseLyricsProvider()
        self._default_providers = (lrclib, qq_music, netease)
        self._cjk_providers = (qq_music, lrclib, netease)

    async def fetch_synced_lyrics(
        self,
        title: str,
        artist: str,
        album: str,
        duration_seconds: float,
    ) -> LyricsResult:
        fallback = LyricsResult(source="在线歌词库")
        failures: list[str] = []
        completed = False
        providers = (
            self._cjk_providers
            if _contains_cjk(title, artist)
            else self._default_providers
        )
        for provider in providers:
            try:
                result = await provider.fetch_synced_lyrics(
                    title,
                    artist,
                    album,
                    duration_seconds,
                )
            except LyricsLookupError as exc:
                failures.append(str(exc))
                continue
            completed = True
            if result.lines or result.instrumental:
                return result
            if result.matched:
                fallback = result
        if completed:
            return fallback
        raise LyricsLookupError("；".join(failures) or "歌词服务暂时不可用")
