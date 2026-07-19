from __future__ import annotations

import asyncio
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from vrctool_app.state import RuntimeState
from vrctool_app.weather import (
    MIN_WEATHER_INTERVAL,
    WeatherError,
    WeatherManager,
    format_weather_message,
    weather_code_label,
)


def fake_weather_request(url: str) -> dict:
    if url == "https://uapis.cn/api/v1/network/myip":
        return {
            "latitude": 31.2304,
            "longitude": 121.4737,
            "region": "中国 上海 上海",
        }
    if url.startswith("https://uapis.cn/api/v1/misc/district"):
        query = parse_qs(urlparse(url).query)
        if query.get("keywords") == ["不存在的城市"]:
            return {"results": []}
        if query.get("keywords"):
            return {
                "results": [
                    {
                        "name": "杭州市",
                        "level": "city",
                        "province": "浙江省",
                        "city": "杭州市",
                        "center": {"lat": 30.2741, "lng": 120.1551},
                    }
                ]
            }
        return {
            "results": [
                {
                    "name": "黄浦区",
                    "level": "district",
                    "province": "上海市",
                    "city": "上海城区",
                    "district": "黄浦区",
                    "center": {"lat": 31.2304, "lng": 121.4737},
                }
            ]
        }
    if url.startswith("https://uapis.cn/api/v1/misc/weather"):
        query = parse_qs(urlparse(url).query)
        is_beijing = "北京" in query.get("city", [""])[0]
        return {
            "province": "北京市" if is_beijing else "上海市",
            "city": "北京城区" if is_beijing else "上海城区",
            "district": "朝阳区" if is_beijing else "黄浦区",
            "adcode": "110105" if is_beijing else "310101",
            "weather": "多云",
            "temperature": 34,
            "humidity": 38,
            "feels_like": 37,
            "precipitation": 0,
            "report_time": "5 分钟前发布",
            "hourly_forecast": [{"wind_speed": 20, "precip": 0}],
        }
    if url == "https://ipapi.co/json/":
        return {
            "latitude": 31.2304,
            "longitude": 121.4737,
            "city": "上海",
            "region": "上海市",
            "country_name": "中国",
        }
    if url.startswith("https://geocoding-api.open-meteo.com/"):
        query = parse_qs(urlparse(url).query)
        if query.get("name") == ["不存在的城市"]:
            return {"results": []}
        return {
            "results": [
                {
                    "name": "杭州",
                    "admin1": "浙江",
                    "country": "中国",
                    "latitude": 30.2741,
                    "longitude": 120.1551,
                }
            ]
        }
    if url.startswith("https://nominatim.openstreetmap.org/reverse"):
        return {"address": {"city": "上海"}}
    if url.startswith("https://api.open-meteo.com/"):
        return {
            "timezone": "Asia/Shanghai",
            "current": {
                "time": "2026-07-15T15:00",
                "temperature_2m": 28.4,
                "apparent_temperature": 31.2,
                "relative_humidity_2m": 72,
                "precipitation": 0.3,
                "weather_code": 61,
                "wind_speed_10m": 9.6,
            },
        }
    raise AssertionError(f"unexpected URL: {url}")


class WeatherFormattingTests(unittest.TestCase):
    def test_weather_code_and_chatbox_message(self) -> None:
        weather = {
            "ready": True,
            "location_name": "上海",
            "condition": weather_code_label(61),
            "temperature": 28.4,
            "feels_like": 31.2,
            "humidity": 72,
            "wind_speed": 9.6,
            "precipitation": 0.3,
        }

        message = format_weather_message(weather)

        self.assertEqual(weather_code_label(61), "小雨")
        self.assertIn("上海天气 | 小雨", message)
        self.assertIn("温度 28.4°C | 体感 31.2°C", message)
        self.assertIn("当前降水 0.3 mm", message)
        self.assertLessEqual(len(message), 240)

    def test_ready_weather_without_a_city_is_not_sent(self) -> None:
        self.assertEqual(
            format_weather_message(
                {
                    "ready": True,
                    "location_name": "",
                    "condition": "晴",
                    "temperature": 25,
                }
            ),
            "",
        )


class WeatherManagerTests(unittest.IsolatedAsyncioTestCase):
    def create_manager(self):
        state = RuntimeState()
        sent: list[str] = []
        manager = WeatherManager(
            state,
            sent.append,
            json_request=fake_weather_request,
        )
        return state, manager, sent

    async def test_ip_location_refreshes_current_weather(self) -> None:
        state, manager, _sent = self.create_manager()

        success = await manager.refresh(auto_locate=True)
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertTrue(weather["ready"])
        self.assertEqual(weather["location_source"], "ip")
        self.assertEqual(weather["location_name"], "上海市黄浦区")
        self.assertEqual(weather["condition"], "小雨")
        self.assertEqual(weather["temperature"], 28.4)
        self.assertEqual(weather["weather_provider"], "Open-Meteo")

    async def test_browser_location_requires_and_keeps_resolved_city(self) -> None:
        state, manager, _sent = self.create_manager()

        success = await manager.use_browser_location(
            31.2304,
            121.4737,
            25.0,
        )
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["location_name"], "上海市黄浦区")
        self.assertEqual(weather["location_source"], "browser")
        self.assertEqual(weather["location_accuracy"], 25.0)
        self.assertTrue(weather["ready"])

    async def test_browser_location_rejects_placeholder_and_clears_values(self) -> None:
        state = RuntimeState()

        def placeholder_city_request(url: str) -> dict:
            if url.startswith("https://uapis.cn/api/v1/misc/district"):
                raise WeatherError("国内城市解析失败")
            if url.startswith("https://nominatim.openstreetmap.org/reverse"):
                return {"address": {"city": "当前位置"}}
            return fake_weather_request(url)

        manager = WeatherManager(
            state,
            lambda _message: None,
            json_request=placeholder_city_request,
        )
        state.patch(
            "weather",
            ready=True,
            location_name="旧城市",
            temperature=20.0,
            last_message="旧天气",
        )

        success = await manager.use_browser_location(31.2, 121.4, 20.0)
        weather = state.snapshot()["weather"]

        self.assertFalse(success)
        self.assertEqual(weather["location_name"], "")
        self.assertIsNone(weather["temperature"])
        self.assertEqual(weather["last_message"], "")
        self.assertFalse(weather["ready"])

    async def test_ip_location_without_city_clears_all_values(self) -> None:
        state = RuntimeState()

        def request_without_city(url: str) -> dict:
            if url == "https://uapis.cn/api/v1/network/myip":
                raise WeatherError("国内 IP 定位失败")
            if url == "https://ipapi.co/json/":
                return {"latitude": 31.2304, "longitude": 121.4737, "city": ""}
            return fake_weather_request(url)

        manager = WeatherManager(state, lambda _message: None, json_request=request_without_city)
        state.patch("weather", ready=True, location_name="旧城市", temperature=20.0)

        success = await manager.refresh(auto_locate=True)
        weather = state.snapshot()["weather"]

        self.assertFalse(success)
        self.assertEqual(weather["location_name"], "")
        self.assertIsNone(weather["temperature"])
        self.assertFalse(weather["ready"])

    async def test_manual_city_search_replaces_location(self) -> None:
        state, manager, _sent = self.create_manager()

        success = await manager.search_city("杭州")
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["location_source"], "manual")
        self.assertEqual(weather["location_name"], "杭州市")
        self.assertAlmostEqual(weather["latitude"], 30.2741)

    async def test_manual_city_search_falls_back_to_open_meteo(self) -> None:
        state = RuntimeState()

        def fallback_search_request(url: str) -> dict:
            if url.startswith("https://uapis.cn/api/v1/misc/district"):
                raise WeatherError("国内城市搜索失败")
            return fake_weather_request(url)

        manager = WeatherManager(
            state,
            lambda _message: None,
            json_request=fallback_search_request,
        )

        success = await manager.search_city("杭州")
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["location_name"], "杭州市")
        self.assertAlmostEqual(weather["latitude"], 30.2741)

    async def test_browser_location_formats_municipality_and_district(self) -> None:
        state = RuntimeState()

        def beijing_request(url: str) -> dict:
            if url.startswith("https://uapis.cn/api/v1/misc/district"):
                return {
                    "results": [
                        {
                            "name": "朝阳区",
                            "level": "district",
                            "province": "北京市",
                            "city": "北京城区",
                            "district": "朝阳区",
                            "center": {"lat": 39.9219, "lng": 116.4436},
                        }
                    ]
                }
            return fake_weather_request(url)

        manager = WeatherManager(state, lambda _message: None, json_request=beijing_request)

        success = await manager.use_browser_location(39.9219, 116.4436, 20.0)
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["location_name"], "北京市朝阳区")

    async def test_open_meteo_403_switches_to_domestic_weather(self) -> None:
        state = RuntimeState()
        requested: list[str] = []

        def blocked_open_meteo_request(url: str) -> dict:
            requested.append(url)
            if url.startswith("https://api.open-meteo.com/"):
                raise WeatherError("天气服务请求失败：HTTP Error 403")
            return fake_weather_request(url)

        manager = WeatherManager(
            state,
            lambda _message: None,
            json_request=blocked_open_meteo_request,
        )
        state.patch(
            "weather",
            latitude=39.9219,
            longitude=116.4436,
            location_name="北京市朝阳区",
            location_source="browser",
        )

        success = await manager.refresh()
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["weather_provider"], "UAPI 国内备用源")
        self.assertEqual(weather["location_name"], "北京市朝阳区")
        self.assertEqual(weather["temperature"], 34.0)
        self.assertEqual(weather["feels_like"], 37.0)
        self.assertEqual(weather["wind_speed"], 20.0)
        self.assertTrue(any("uapis.cn/api/v1/misc/weather" in url for url in requested))

    async def test_domestic_reverse_failure_falls_back_to_nominatim_hierarchy(self) -> None:
        state = RuntimeState()

        def fallback_request(url: str) -> dict:
            if url.startswith("https://uapis.cn/api/v1/misc/district"):
                raise WeatherError("国内城市解析失败")
            if url.startswith("https://nominatim.openstreetmap.org/reverse"):
                return {
                    "address": {
                        "state": "浙江省",
                        "city": "杭州市",
                        "county": "西湖区",
                    }
                }
            return fake_weather_request(url)

        manager = WeatherManager(state, lambda _message: None, json_request=fallback_request)

        success = await manager.use_browser_location(30.2741, 120.1551, 30.0)

        self.assertTrue(success)
        self.assertEqual(state.snapshot()["weather"]["location_name"], "杭州市西湖区")

    async def test_missing_manual_city_clears_previous_weather(self) -> None:
        state, manager, _sent = self.create_manager()
        state.patch("weather", ready=True, location_name="旧城市", temperature=20.0)

        with self.assertRaises(WeatherError):
            await manager.search_city("不存在的城市")
        weather = state.snapshot()["weather"]

        self.assertEqual(weather["location_name"], "")
        self.assertIsNone(weather["temperature"])
        self.assertFalse(weather["ready"])

    async def test_broadcast_sends_immediately_clamps_interval_and_cleans_task(self) -> None:
        state, manager, sent = self.create_manager()

        await manager.configure(True, 1)
        for _ in range(50):
            if sent:
                break
            await asyncio.sleep(0.01)

        task = manager._broadcast_task
        self.assertEqual(state.snapshot()["weather"]["interval"], MIN_WEATHER_INTERVAL)
        self.assertEqual(len(sent), 1)
        self.assertIn("上海", sent[0])
        self.assertIn("天气 | 小雨", sent[0])
        self.assertIsNotNone(task)
        self.assertFalse(task.done())

        await manager.shutdown()

        self.assertIsNone(manager._broadcast_task)
        self.assertTrue(task.cancelled())

    async def test_refresh_failure_preserves_last_valid_weather(self) -> None:
        state, manager, _sent = self.create_manager()
        state.patch(
            "weather",
            ready=True,
            latitude=31.2304,
            longitude=121.4737,
            location_name="上海市黄浦区",
            temperature=28.4,
            condition="小雨",
            last_update="10:00:00",
            last_message="previous weather",
        )

        def fail_request(_url: str) -> dict:
            raise RuntimeError("temporary network failure")

        manager._json_request = fail_request
        success = await manager.refresh()
        weather = state.snapshot()["weather"]

        self.assertFalse(success)
        self.assertTrue(weather["ready"])
        self.assertEqual(weather["temperature"], 28.4)
        self.assertEqual(weather["condition"], "小雨")
        self.assertEqual(weather["last_update"], "10:00:00")
        self.assertEqual(weather["last_message"], "previous weather")
        self.assertEqual(weather["status"], "更新失败，继续使用上次数据")

    async def test_broadcast_reuses_valid_weather_after_unexpected_refresh_error(self) -> None:
        state, manager, sent = self.create_manager()
        state.patch(
            "weather",
            broadcast_enabled=True,
            ready=True,
            latitude=31.2304,
            longitude=121.4737,
            location_name="上海市黄浦区",
            temperature=28.4,
            feels_like=31.2,
            humidity=72,
            wind_speed=9.6,
            precipitation=0.3,
            condition="小雨",
        )

        with patch.object(manager, "refresh", new=AsyncMock(side_effect=RuntimeError("boom"))):
            self.assertTrue(await manager._broadcast_once())

        self.assertEqual(len(sent), 1)
        self.assertIn("上海市黄浦区天气", sent[0])
        self.assertIn("温度 28.4°C", sent[0])


if __name__ == "__main__":
    unittest.main()
