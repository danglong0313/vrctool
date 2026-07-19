from __future__ import annotations

import asyncio
import json
import os
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
DOMESTIC_IP_LOCATION_URL = os.environ.get(
    "VRCTOOL_DOMESTIC_IP_LOCATION_URL",
    "https://uapis.cn/api/v1/network/myip",
)
DOMESTIC_DISTRICT_URL = os.environ.get(
    "VRCTOOL_DOMESTIC_DISTRICT_URL",
    "https://uapis.cn/api/v1/misc/district",
)
DOMESTIC_WEATHER_URL = os.environ.get(
    "VRCTOOL_DOMESTIC_WEATHER_URL",
    "https://uapis.cn/api/v1/misc/weather",
)
REVERSE_GEOCODING_URL = os.environ.get(
    "VRCTOOL_REVERSE_GEOCODING_URL",
    "https://nominatim.openstreetmap.org/reverse",
)
USER_AGENT = f"vrctool/{__version__} (+https://github.com/danglong0313/vrctool)"

DIRECT_MUNICIPALITIES = {"北京市", "上海市", "天津市", "重庆市"}
CHINESE_ADMIN_SUFFIXES = (
    "特别行政区",
    "自治区",
    "自治州",
    "地区",
    "市",
    "区",
    "县",
    "盟",
    "旗",
    "省",
)
MUNICIPALITY_ALIASES = {
    "北京": "北京市",
    "上海": "上海市",
    "天津": "天津市",
    "重庆": "重庆市",
}
MUNICIPALITY_BY_ISO_CODE = {
    "CN-BJ": "北京市",
    "CN-SH": "上海市",
    "CN-TJ": "天津市",
    "CN-CQ": "重庆市",
}

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
    location = str(weather.get("location_name") or "").strip()
    if not weather.get("ready") or not location:
        return ""
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
        self._location_lock = asyncio.Lock()
        self._city_cache: dict[tuple[float, float], str] = {}
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
            previous = self.state.snapshot()["weather"]
            had_valid_weather = bool(
                previous.get("ready")
                and str(previous.get("location_name") or "").strip()
                and previous.get("temperature") is not None
            )
            preserve_previous = had_valid_weather and not auto_locate
            updates = {"updating": True, "status": "更新中", "error": ""}
            if auto_locate:
                updates.update(self._empty_location_values())
                updates.update(self._empty_weather_values())
            elif not had_valid_weather:
                updates.update(self._empty_weather_values())
            self.state.patch("weather", **updates)
            try:
                snapshot = self.state.snapshot()["weather"]
                latitude = snapshot.get("latitude")
                longitude = snapshot.get("longitude")
                location_name = str(snapshot.get("location_name") or "").strip()
                if auto_locate or not location_name:
                    location = await asyncio.to_thread(self._locate_by_ip)
                    latitude = location["latitude"]
                    longitude = location["longitude"]
                    self.state.patch("weather", **location)
                    location_name = str(location.get("location_name") or "").strip()
                if not location_name:
                    raise WeatherError("无法识别所在城市")
                weather = await asyncio.to_thread(
                    self._fetch_current_weather,
                    float(latitude) if latitude is not None else None,
                    float(longitude) if longitude is not None else None,
                    location_name,
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
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure_values = (
                    self._empty_weather_values()
                    if not preserve_previous
                    else {"ready": True}
                )
                self.state.patch(
                    "weather",
                    **failure_values,
                    updating=False,
                    status=("更新失败，继续使用上次数据" if preserve_previous else "更新失败"),
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
        async with self._location_lock:
            self.state.patch("weather", updating=True, status="正在识别城市", error="")
            try:
                latitude, longitude = self._validate_coordinates(latitude, longitude)
                city = await asyncio.to_thread(
                    self._reverse_geocode_city,
                    latitude,
                    longitude,
                )
            except WeatherError as exc:
                self._clear_unresolved_location(str(exc))
                return False
            self.state.patch(
                "weather",
                **self._empty_weather_values(),
                latitude=latitude,
                longitude=longitude,
                location_name=city,
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
        try:
            location = await asyncio.to_thread(self._search_city_domestic, query)
        except WeatherError as domestic_error:
            try:
                location = await asyncio.to_thread(self._search_city_open_meteo, query)
                self.state.log("warn", f"国内城市搜索不可用，已切换 Open-Meteo：{domestic_error}")
            except WeatherError as open_meteo_error:
                error = f"城市搜索失败：{domestic_error}；{open_meteo_error}"
                self._clear_unresolved_location(error)
                raise WeatherError(error) from open_meteo_error
        self.state.patch(
            "weather",
            **self._empty_weather_values(),
            **location,
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
            await self._broadcast_once()
            weather = self.state.snapshot()["weather"]
            try:
                interval = float(weather.get("interval") or DEFAULT_WEATHER_INTERVAL)
            except (TypeError, ValueError):
                interval = DEFAULT_WEATHER_INTERVAL
            interval = max(MIN_WEATHER_INTERVAL, min(interval, MAX_WEATHER_INTERVAL))
            await asyncio.sleep(interval)

    async def _broadcast_once(self) -> bool:
        snapshot = self.state.snapshot()["weather"]
        try:
            await self.refresh(
                auto_locate=not str(snapshot.get("location_name") or "").strip()
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.patch(
                "weather",
                updating=False,
                status="更新失败，继续等待重试",
                error=str(exc),
            )
            self.state.log("err", f"天气广播任务异常，稍后重试：{exc}")

        weather = self.state.snapshot()["weather"]
        try:
            message = format_weather_message(weather)
        except Exception as exc:
            self.state.patch("weather", error=f"天气消息生成失败：{exc}")
            self.state.log("err", f"天气消息生成失败：{exc}")
            return False
        if not message:
            return False
        try:
            self.send_message(message)
        except Exception as exc:
            self.state.patch("weather", error=f"ChatBox 发送失败：{exc}")
            self.state.log("err", f"天气 ChatBox 发送失败：{exc}")
            return False
        self.state.patch(
            "weather",
            last_sent=datetime.now().strftime("%H:%M:%S"),
            last_message=message,
        )
        return True

    def _locate_by_ip(self) -> dict[str, Any]:
        try:
            return self._locate_by_domestic_ip()
        except WeatherError as domestic_error:
            try:
                location = self._locate_by_ipapi()
                self.state.log("warn", f"国内 IP 定位不可用，已切换 ipapi：{domestic_error}")
                return location
            except WeatherError as ipapi_error:
                raise WeatherError(
                    f"IP 定位服务均不可用：{domestic_error}；{ipapi_error}"
                ) from ipapi_error

    def _locate_by_domestic_ip(self) -> dict[str, Any]:
        data = self._json_request(DOMESTIC_IP_LOCATION_URL)
        latitude, longitude = self._validate_coordinates(
            data.get("latitude"),
            data.get("longitude"),
        )
        location_name = ""
        try:
            location_name = self._reverse_geocode_city(latitude, longitude)
        except WeatherError:
            region_parts = [part for part in str(data.get("region") or "").split() if part]
            province = region_parts[-2] if len(region_parts) >= 2 else ""
            city = region_parts[-1] if region_parts else ""
            location_name = self._format_location_name(province, city, "")
        if not location_name:
            raise WeatherError("国内 IP 定位无法识别所在城市")
        return {
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name,
            "location_source": "ip",
            "location_accuracy": 0.0,
        }

    def _locate_by_ipapi(self) -> dict[str, Any]:
        data = self._json_request(IP_LOCATION_URL)
        if data.get("error"):
            raise WeatherError(str(data.get("reason") or "IP 定位失败"))
        latitude, longitude = self._validate_coordinates(
            data.get("latitude"),
            data.get("longitude"),
        )
        location_name = self._format_location_name(
            data.get("region"),
            data.get("city"),
            data.get("district"),
        )
        if not location_name:
            raise WeatherError("IP 定位无法识别所在城市")
        return {
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name,
            "location_source": "ip",
            "location_accuracy": 0.0,
        }

    def _fetch_current_weather(
        self,
        latitude: Optional[float],
        longitude: Optional[float],
        location_name: str,
    ) -> dict[str, Any]:
        primary_error: Optional[WeatherError] = None
        if latitude is not None and longitude is not None:
            try:
                return self._fetch_open_meteo_weather(latitude, longitude)
            except WeatherError as exc:
                primary_error = exc
        try:
            weather = self._fetch_domestic_weather(location_name)
        except WeatherError as domestic_error:
            if primary_error:
                raise WeatherError(
                    f"天气主服务和国内备用源均不可用：{primary_error}；{domestic_error}"
                ) from domestic_error
            raise
        if primary_error:
            self.state.log("warn", f"Open-Meteo 不可用，已切换国内天气源：{primary_error}")
        return weather

    def _fetch_open_meteo_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
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
                "weather_provider": "Open-Meteo",
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherError("当前天气数据不完整") from exc

    def _fetch_domestic_weather(self, location_name: str) -> dict[str, Any]:
        params = urlencode(
            {
                "city": location_name[:80],
                "extended": "true",
                "hourly": "true",
                "lang": "zh",
            }
        )
        data = self._json_request(f"{DOMESTIC_WEATHER_URL}?{params}")
        hourly = data.get("hourly_forecast")
        current_hour = hourly[0] if isinstance(hourly, list) and hourly else {}
        if not isinstance(current_hour, dict):
            current_hour = {}
        try:
            temperature = float(data["temperature"])
            condition = self._valid_city_name(data.get("weather"))
            if not condition:
                raise ValueError("missing weather description")
            weather = {
                "temperature": temperature,
                "feels_like": float(data.get("feels_like", temperature)),
                "humidity": int(float(data["humidity"])),
                "precipitation": float(
                    data.get("precipitation", current_hour.get("precip", 0.0)) or 0.0
                ),
                "wind_speed": float(current_hour.get("wind_speed", 0.0) or 0.0),
                "weather_code": None,
                "condition": condition,
                "timezone": "Asia/Shanghai" if data.get("adcode") else "",
                "weather_time": str(data.get("report_time") or current_hour.get("time") or ""),
                "weather_provider": "UAPI 国内备用源",
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherError("国内天气源返回的数据不完整") from exc
        resolved_name = self._format_location_name(
            data.get("province"),
            data.get("city"),
            data.get("district"),
        )
        if resolved_name:
            weather["location_name"] = resolved_name
        return weather

    def _reverse_geocode_city(self, latitude: float, longitude: float) -> str:
        cache_key = (round(latitude, 3), round(longitude, 3))
        cached = self._city_cache.get(cache_key)
        if cached:
            return cached
        domestic_error: Optional[WeatherError] = None
        params = urlencode(
            {
                "lat": f"{latitude:.6f}",
                "lng": f"{longitude:.6f}",
                "limit": 8,
            }
        )
        try:
            data = self._json_request(f"{DOMESTIC_DISTRICT_URL}?{params}")
            city = self._location_from_district_results(data)
            self._city_cache[cache_key] = city
            return city
        except WeatherError as exc:
            domestic_error = exc
        params = urlencode(
            {
                "lat": f"{latitude:.6f}",
                "lon": f"{longitude:.6f}",
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": 14,
                "accept-language": "zh-CN,zh,en",
            }
        )
        try:
            data = self._json_request(f"{REVERSE_GEOCODING_URL}?{params}")
            city = self._location_from_nominatim(data)
        except WeatherError as nominatim_error:
            raise WeatherError(
                f"城市解析服务均不可用：{domestic_error}；{nominatim_error}"
            ) from nominatim_error
        self._city_cache[cache_key] = city
        return city

    def _search_city_domestic(self, query: str) -> dict[str, Any]:
        params = urlencode({"keywords": query[:80], "limit": 5})
        data = self._json_request(f"{DOMESTIC_DISTRICT_URL}?{params}")
        result = self._first_district_result(data)
        center = result.get("center")
        if not isinstance(center, dict):
            raise WeatherError("国内城市搜索没有返回有效坐标")
        latitude, longitude = self._validate_coordinates(center.get("lat"), center.get("lng"))
        location_name = self._location_from_district_result(result)
        return {
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name,
        }

    def _search_city_open_meteo(self, query: str) -> dict[str, Any]:
        params = urlencode(
            {
                "name": query[:80],
                "count": 1,
                "language": "zh",
                "format": "json",
            }
        )
        data = self._json_request(f"{GEOCODING_URL}?{params}")
        results = data.get("results")
        if not isinstance(results, list) or not results:
            raise WeatherError("没有找到这个城市")
        result = results[0]
        latitude, longitude = self._validate_coordinates(
            result.get("latitude"),
            result.get("longitude"),
        )
        city_name = result.get("name")
        if str(result.get("country_code") or "").upper() == "CN" or str(
            result.get("country") or ""
        ) in {"中国", "中华人民共和国"}:
            city_name = self._ensure_chinese_city_suffix(city_name)
        location_name = self._format_location_name(
            result.get("admin1"),
            city_name,
            result.get("admin2"),
        )
        if not location_name:
            raise WeatherError("无法识别所在城市")
        return {
            "latitude": latitude,
            "longitude": longitude,
            "location_name": location_name,
        }

    def _location_from_district_results(self, data: dict[str, Any]) -> str:
        return self._location_from_district_result(self._first_district_result(data))

    @staticmethod
    def _first_district_result(data: dict[str, Any]) -> dict[str, Any]:
        results = data.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise WeatherError("国内城市解析服务没有返回行政区")
        return results[0]

    def _location_from_district_result(self, result: dict[str, Any]) -> str:
        district = result.get("district")
        if not district and str(result.get("level") or "") == "district":
            district = result.get("name")
        location_name = self._format_location_name(
            result.get("province"),
            result.get("city"),
            district,
        )
        if not location_name:
            location_name = self._valid_city_name(result.get("name"))
        if not location_name:
            raise WeatherError("国内城市解析服务无法识别所在城市")
        return location_name

    def _location_from_nominatim(self, data: dict[str, Any]) -> str:
        address = data.get("address")
        if not isinstance(address, dict):
            raise WeatherError("OpenStreetMap 没有返回地址")
        iso_code = str(address.get("ISO3166-2-lvl4") or "").upper()
        province = address.get("state") or address.get("province")
        province = MUNICIPALITY_BY_ISO_CODE.get(iso_code, province)
        city = address.get("city") or address.get("town") or address.get("municipality")
        district = address.get("city_district") or address.get("county")
        location_name = self._format_location_name(province, city, district)
        if not location_name:
            raise WeatherError("OpenStreetMap 无法识别所在城市")
        return location_name

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
    def _valid_city_name(value: Any) -> str:
        name = str(value or "").strip()[:80]
        if name.casefold() in {"当前位置", "当前位置天气", "current location"}:
            return ""
        return name

    @classmethod
    def _format_location_name(cls, province: Any, city: Any, district: Any) -> str:
        province_name = cls._valid_city_name(province)
        city_name = cls._valid_city_name(city)
        district_name = cls._valid_city_name(district)
        province_name = MUNICIPALITY_ALIASES.get(province_name, province_name)
        if not province_name and city_name in MUNICIPALITY_ALIASES:
            province_name = MUNICIPALITY_ALIASES[city_name]

        if province_name in DIRECT_MUNICIPALITIES:
            if not district_name and city_name.endswith(("区", "县")):
                district_name = city_name
            return cls._join_location_parts(province_name, district_name)

        primary = city_name or province_name
        return cls._join_location_parts(primary, district_name)

    @staticmethod
    def _join_location_parts(primary: str, secondary: str) -> str:
        if not primary:
            return secondary
        if not secondary or secondary == primary:
            return primary
        if secondary.startswith(primary):
            return secondary
        if primary.endswith(secondary):
            return primary
        return f"{primary}{secondary}"[:80]

    @classmethod
    def _ensure_chinese_city_suffix(cls, value: Any) -> str:
        name = cls._valid_city_name(value)
        if not name or name.endswith(CHINESE_ADMIN_SUFFIXES):
            return name
        if any("\u4e00" <= character <= "\u9fff" for character in name):
            return f"{name}市"[:80]
        return name

    @staticmethod
    def _empty_location_values() -> dict[str, Any]:
        return {
            "latitude": None,
            "longitude": None,
            "location_name": "",
            "location_source": "",
            "location_accuracy": 0.0,
        }

    @staticmethod
    def _empty_weather_values() -> dict[str, Any]:
        return {
            "ready": False,
            "temperature": None,
            "feels_like": None,
            "humidity": None,
            "precipitation": None,
            "wind_speed": None,
            "weather_code": None,
            "condition": "",
            "timezone": "",
            "weather_time": "",
            "weather_provider": "",
            "last_update": "",
            "last_message": "",
        }

    def _clear_unresolved_location(self, error: str) -> None:
        self.state.patch(
            "weather",
            **self._empty_location_values(),
            **self._empty_weather_values(),
            updating=False,
            status="定位失败",
            error=error,
        )
