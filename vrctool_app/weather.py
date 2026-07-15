from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vrctool_app import __version__
from vrctool_app.state import RuntimeState


DEFAULT_WEATHER_INTERVAL = 600.0
MIN_WEATHER_INTERVAL = 300.0
MAX_WEATHER_INTERVAL = 3600.0
IP_LOCATION_URL = "https://ipapi.co/json/"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = f"vrctool/{__version__} (+https://github.com/danglong0313/vrctool)"

WEATHER_CODE_LABELS = {
    0: "晴",
    1: "晴间少云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


class WeatherError(RuntimeError):
    pass


def weather_code_label(code: int) -> str:
    return WEATHER_CODE_LABELS.get(int(code), "未知天气")


def format_weather_message(weather: dict[str, Any]) -> str:
    if not weather.get("ready"):
        return ""
    location = str(weather.get("location_name") or "当前位置")
    condition = str(weather.get("condition") or "未知天气")
    temperature = float(weather.get("temperature") or 0.0)
    feels_like = float(weather.get("feels_like") or 0.0)
    humidity = int(weather.get("humidity") or 0)
    wind_speed = float(weather.get("wind_speed") or 0.0)
    precipitation = float(weather.get("precipitation") or 0.0)
    lines = [
        f"{location}天气 | {condition}",
        f"温度 {temperature:.1f}°C | 体感 {feels_like:.1f}°C",
        f"湿度 {humidity}% | 风速 {wind_speed:.1f} km/h",
    ]
    if precipitation > 0:
        lines.append(f"当前降水 {precipitation:.1f} mm")
    return "\n".join(lines)[:240]


def request_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = response.read(1_000_001)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise WeatherError(f"天气服务请求失败：{exc}") from exc
    if len(payload) > 1_000_000:
        raise WeatherError("天气服务返回的数据过大")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeatherError("天气服务返回了无效数据") from exc
    if not isinstance(parsed, dict):
        raise WeatherError("天气服务返回格式不正确")
    return parsed


class WeatherManager:
    def __init__(
        self,
        state: RuntimeState,
        send_message: Callable[[str], Any],
        *,
        json_request: Callable[[str], dict[str, Any]] = request_json,
    ) -> None:
        self.state = state
        self.send_message = send_message
        self._json_request = json_request
        self._refresh_lock = asyncio.Lock()
        self._broadcast_task: Optional[asyncio.Task] = None
        self._startup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self.state.snapshot()["weather"].get("broadcast_enabled"):
            self._ensure_broadcast_task()
        else:
            self._startup_task = asyncio.create_task(
                self.refresh(auto_locate=True),
                name="vrctool-weather-initial-refresh",
            )

    async def configure(self, enabled: bool, interval: float) -> None:
        interval = max(MIN_WEATHER_INTERVAL, min(float(interval), MAX_WEATHER_INTERVAL))
        self.state.patch(
            "weather",
            broadcast_enabled=bool(enabled),
            interval=interval,
        )
        await self._stop_broadcast_task()
        if enabled:
            self._ensure_broadcast_task()
            self.state.log("ok", f"天气 ChatBox 广播已开启，每 {interval / 60:g} 分钟更新一次")
        else:
            self.state.log("ok", "天气 ChatBox 广播已关闭")

    async def refresh(self, auto_locate: bool = False) -> bool:
        async with self._refresh_lock:
            self.state.patch("weather", updating=True, status="更新中", error="")
            try:
                snapshot = self.state.snapshot()["weather"]
                latitude = snapshot.get("latitude")
                longitude = snapshot.get("longitude")
                if auto_locate or latitude is None or longitude is None:
                    location = await asyncio.to_thread(self._locate_by_ip)
                    latitude = location["latitude"]
                    longitude = location["longitude"]
                    self.state.patch("weather", **location)
                weather = await asyncio.to_thread(
                    self._fetch_current_weather,
                    float(latitude),
                    float(longitude),
                )
                self.state.patch(
                    "weather",
                    **weather,
                    ready=True,
                    updating=False,
                    status="已更新",
                    error="",
                    last_update=datetime.now().strftime("%H:%M:%S"),
                )
                return True
            except (WeatherError, TypeError, ValueError) as exc:
                self.state.patch(
                    "weather",
                    ready=False,
                    updating=False,
                    status="更新失败",
                    error=str(exc),
                )
                self.state.log("err", f"天气更新失败：{exc}")
                return False

    async def use_browser_location(
        self,
        latitude: float,
        longitude: float,
        accuracy: Optional[float] = None,
    ) -> bool:
        latitude, longitude = self._validate_coordinates(latitude, longitude)
        self.state.patch(
            "weather",
            latitude=latitude,
            longitude=longitude,
            location_name="当前位置",
            location_source="browser",
            location_accuracy=max(0.0, float(accuracy or 0.0)),
        )
        return await self.refresh()

    async def use_ip_location(self) -> bool:
        return await self.refresh(auto_locate=True)

    async def search_city(self, query: str) -> bool:
        query = str(query or "").strip()
        if not query:
            raise WeatherError("请输入城市名称")
        params = urlencode(
            {
                "name": query[:80],
                "count": 1,
                "language": "zh",
                "format": "json",
            }
        )
        data = await asyncio.to_thread(self._json_request, f"{GEOCODING_URL}?{params}")
        results = data.get("results")
        if not isinstance(results, list) or not results:
            raise WeatherError("没有找到这个城市")
        result = results[0]
        latitude, longitude = self._validate_coordinates(
            result.get("latitude"),
            result.get("longitude"),
        )
        location_name = self._location_name(
            result.get("name"),
            result.get("admin1"),
            result.get("country"),
        )
        self.state.patch(
            "weather",
            latitude=latitude,
            longitude=longitude,
            location_name=location_name or query,
            location_source="manual",
            location_accuracy=0.0,
        )
        return await self.refresh()

    async def shutdown(self) -> None:
        await self._stop_task("_startup_task")
        await self._stop_broadcast_task()

    def _ensure_broadcast_task(self) -> None:
        if self._broadcast_task and not self._broadcast_task.done():
            return
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(),
            name="vrctool-weather-chatbox",
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
        while self.state.snapshot()["weather"].get("broadcast_enabled"):
            snapshot = self.state.snapshot()["weather"]
            success = await self.refresh(
                auto_locate=snapshot.get("latitude") is None or snapshot.get("longitude") is None
            )
            weather = self.state.snapshot()["weather"]
            if success:
                message = format_weather_message(weather)
                if message:
                    try:
                        self.send_message(message)
                        self.state.patch(
                            "weather",
                            last_sent=datetime.now().strftime("%H:%M:%S"),
                            last_message=message,
                        )
                    except Exception as exc:
                        self.state.patch("weather", error=f"ChatBox 发送失败：{exc}")
                        self.state.log("err", f"天气 ChatBox 发送失败：{exc}")
            interval = max(
                MIN_WEATHER_INTERVAL,
                float(weather.get("interval") or DEFAULT_WEATHER_INTERVAL),
            )
            await asyncio.sleep(interval)

    def _locate_by_ip(self) -> dict[str, Any]:
        data = self._json_request(IP_LOCATION_URL)
        if data.get("error"):
            raise WeatherError(str(data.get("reason") or "IP 定位失败"))
        latitude, longitude = self._validate_coordinates(
            data.get("latitude"),
            data.get("longitude"),
        )
        location_name = self._location_name(
            data.get("city"),
            data.get("region"),
            data.get("country_name"),
        )
        return {
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name or "当前位置",
            "location_source": "ip",
            "location_accuracy": 0.0,
        }

    def _fetch_current_weather(self, latitude: float, longitude: float) -> dict[str, Any]:
        params = urlencode(
            {
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "precipitation,weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        data = self._json_request(f"{WEATHER_URL}?{params}")
        current = data.get("current")
        if not isinstance(current, dict):
            raise WeatherError("天气服务没有返回当前天气")
        try:
            code = int(current["weather_code"])
            return {
                "temperature": float(current["temperature_2m"]),
                "feels_like": float(current["apparent_temperature"]),
                "humidity": int(current["relative_humidity_2m"]),
                "precipitation": float(current["precipitation"]),
                "wind_speed": float(current["wind_speed_10m"]),
                "weather_code": code,
                "condition": weather_code_label(code),
                "timezone": str(data.get("timezone") or ""),
                "weather_time": str(current.get("time") or ""),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherError("当前天气数据不完整") from exc

    @staticmethod
    def _validate_coordinates(latitude: Any, longitude: Any) -> tuple[float, float]:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError) as exc:
            raise WeatherError("定位服务没有返回有效坐标") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise WeatherError("定位坐标超出有效范围")
        return latitude, longitude

    @staticmethod
    def _location_name(*parts: Any) -> str:
        names: list[str] = []
        for part in parts:
            name = str(part or "").strip()
            if name and name.casefold() not in {item.casefold() for item in names}:
                names.append(name)
        return " · ".join(names[:2])
