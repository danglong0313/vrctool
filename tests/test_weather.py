from __future__ import annotations

import asyncio
import unittest
from urllib.parse import parse_qs, urlparse

from vrctool_app.state import RuntimeState
from vrctool_app.weather import (
    MIN_WEATHER_INTERVAL,
    WeatherError,
    WeatherManager,
    format_weather_message,
    weather_code_label,
)


def fake_weather_request(url: str) -> dict:
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
        self.assertEqual(weather["location_name"], "上海")
        self.assertEqual(weather["condition"], "小雨")
        self.assertEqual(weather["temperature"], 28.4)

    async def test_browser_location_requires_and_keeps_resolved_city(self) -> None:
        state, manager, _sent = self.create_manager()

        success = await manager.use_browser_location(
            31.2304,
            121.4737,
            25.0,
        )
        weather = state.snapshot()["weather"]

        self.assertTrue(success)
        self.assertEqual(weather["location_name"], "上海")
        self.assertEqual(weather["location_source"], "browser")
        self.assertEqual(weather["location_accuracy"], 25.0)
        self.assertTrue(weather["ready"])

    async def test_browser_location_rejects_placeholder_and_clears_values(self) -> None:
        state = RuntimeState()

        def placeholder_city_request(url: str) -> dict:
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
        self.assertEqual(weather["location_name"], "杭州")
        self.assertAlmostEqual(weather["latitude"], 30.2741)

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


if __name__ == "__main__":
    unittest.main()
