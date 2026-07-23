from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from vrctool_app.chatbox import ChatboxManager
from vrctool_app.state import RuntimeState


def device_sample(cpu_usage: float = 20.0) -> dict:
    return {
        "cpu": {"name": "CPU", "usage": cpu_usage},
        "gpu": {
            "name": "GPU",
            "usage": 30.0,
            "vram_used": 2.0,
            "vram_total": 8.0,
        },
        "ram": {"used": 4.0, "total": 16.0, "usage": 25.0},
    }


class FakeUdpClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, list[object]]] = []

    def send_message(self, address: str, payload: list[object]) -> None:
        self.messages.append((address, payload))


class ChatboxBatchTests(unittest.TestCase):
    def create_manager(self) -> tuple[RuntimeState, ChatboxManager, FakeUdpClient]:
        state = RuntimeState()
        manager = ChatboxManager(state)
        client = FakeUdpClient()
        manager._client._sock.close()
        manager._client = client
        return state, manager, client

    def test_single_enabled_source_is_repeated_by_batch_scheduler(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
        )

        sent = manager.send_message("custom", source="custom")

        self.assertFalse(sent)
        self.assertEqual(client.messages, [])
        self.assertTrue(state.snapshot()["chatbox"]["batch_running"])
        for _ in range(3):
            self.assertTrue(manager.send_next_batch())
        self.assertEqual([item[1][0] for item in client.messages], ["custom"] * 3)

    def test_multiple_sources_are_sent_in_fixed_round_robin_order(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
            device_enabled=True,
        )
        self.assertFalse(manager.send_message("custom", source="custom"))
        self.assertFalse(manager.send_message("device", source="device"))
        self.assertEqual(client.messages, [])

        with patch("vrctool_app.chatbox.get_device_info", return_value=device_sample()):
            self.assertTrue(manager.send_next_batch())
            self.assertTrue(manager.send_next_batch())
            self.assertTrue(manager.send_next_batch())

        payloads = [message[1][0] for message in client.messages]
        self.assertEqual(payloads[0], "custom")
        self.assertIn("CPU 20.00%", payloads[1])
        self.assertEqual(payloads[2], "custom")
        self.assertEqual(state.snapshot()["chatbox"]["batch_next_source"], "device")

    def test_batch_keeps_only_the_latest_message_for_each_source(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="new",
            device_enabled=True,
        )
        manager.send_message("old", source="custom")
        manager.send_message("new", source="custom")
        manager.send_message("device", source="device")

        manager.send_next_batch()

        self.assertEqual(client.messages[0][1][0], "new")

    def test_batch_renders_live_heart_rate_when_its_turn_arrives(self) -> None:
        state, manager, client = self.create_manager()
        state.patch("chatbox", batch_enabled=True)
        state.patch(
            "heart_rate",
            send_enabled=True,
            connected=True,
            bpm=72,
            device_name="Heart Sensor",
        )
        manager.send_message("心率: 72 BPM", source="heart_rate")
        state.patch("heart_rate", bpm=89)

        self.assertTrue(manager.send_next_batch())

        self.assertIn("89 BPM", client.messages[0][1][0])
        self.assertNotIn("72 BPM", client.messages[0][1][0])

    def test_batch_renders_live_device_and_performance_state(self) -> None:
        state, manager, client = self.create_manager()
        state.patch("chatbox", batch_enabled=True, device_enabled=True)
        state.patch(
            "device",
            cpu={"name": "CPU", "usage": 10.0},
            gpu={"name": "GPU", "usage": 20.0, "vram_used": 2.0, "vram_total": 8.0},
            ram={"used": 4.0, "total": 16.0, "usage": 25.0},
        )
        state.patch(
            "performance",
            broadcast_enabled=True,
            vrchat_running=True,
            sampling=True,
            fps=72.0,
            avg_fps=70.0,
            frame_ms=13.9,
        )
        manager.send_message("old device", source="device")
        manager.send_message("old fps", source="performance")
        state.patch("device", cpu={"name": "CPU", "usage": 88.0})
        state.patch("performance", fps=91.0, frame_ms=11.0)

        with patch(
            "vrctool_app.chatbox.get_device_info",
            return_value=device_sample(cpu_usage=88.0),
        ) as get_info:
            self.assertTrue(manager.send_next_batch())
            self.assertTrue(manager.send_next_batch())

        payloads = [item[1][0] for item in client.messages]
        self.assertIn("CPU 88.00%", payloads[0])
        self.assertIn("FPS: 91.0", payloads[1])
        self.assertIn("Frame: 11.0ms", payloads[1])
        self.assertEqual(get_info.call_count, 1)
        self.assertEqual(state.snapshot()["device"]["cpu"]["usage"], 88.0)

    def test_disabling_batch_restores_independent_sends(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=False,
            custom_enabled=True,
            custom_message="custom",
            device_enabled=True,
        )

        custom_sent = manager.send_message("custom", source="custom")
        device_sent = manager.send_message("device", source="device")

        self.assertTrue(custom_sent)
        self.assertTrue(device_sent)
        self.assertEqual([item[1][0] for item in client.messages], ["custom", "device"])

    def test_unavailable_performance_source_is_removed_from_rotation(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
            device_enabled=True,
        )
        state.patch(
            "performance",
            broadcast_enabled=True,
            vrchat_running=True,
            sampling=True,
        )
        manager.send_message("custom", source="custom")
        manager.send_message("device", source="device")
        manager.send_message("fps", source="performance")
        state.patch("performance", vrchat_running=False, sampling=False)

        with patch("vrctool_app.chatbox.get_device_info", return_value=device_sample()):
            manager.send_next_batch()
            manager.send_next_batch()
            manager.send_next_batch()

        payloads = [item[1][0] for item in client.messages]
        self.assertEqual(payloads[0], "custom")
        self.assertIn("CPU 20.00%", payloads[1])
        self.assertEqual(payloads[2], "custom")

    def test_weather_remains_in_round_robin_after_its_batch_turn(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
        )
        state.patch(
            "weather",
            broadcast_enabled=True,
            ready=True,
            location_name="上海市",
            condition="小雨",
            temperature=28.4,
            feels_like=31.2,
            humidity=72,
            wind_speed=9.6,
            precipitation=0.3,
        )
        manager.send_message("custom", source="custom")
        manager.send_message("weather", source="weather")

        manager.send_next_batch()
        manager.send_next_batch()
        state.patch("weather", temperature=30.5)
        manager.send_next_batch()
        manager.send_next_batch()

        payloads = [item[1][0] for item in client.messages]
        self.assertEqual(payloads[0], "custom")
        self.assertIn("温度 28.4°C", payloads[1])
        self.assertEqual(payloads[2], "custom")
        self.assertIn("温度 30.5°C", payloads[3])
        self.assertEqual(manager._batch_messages["weather"], payloads[3])

    def test_single_weather_source_keeps_repeating_between_refreshes(self) -> None:
        state, manager, client = self.create_manager()
        state.patch("chatbox", batch_enabled=True)
        state.patch(
            "weather",
            broadcast_enabled=True,
            ready=True,
            location_name="上海市",
            condition="晴",
            temperature=30.0,
            feels_like=31.0,
            humidity=60,
            wind_speed=5.0,
            precipitation=0.0,
        )
        manager.send_message("weather seed", source="weather")

        for _ in range(3):
            self.assertTrue(manager.send_next_batch())

        payloads = [item[1][0] for item in client.messages]
        self.assertEqual(len(payloads), 3)
        self.assertTrue(all("上海市天气" in payload for payload in payloads))
        self.assertTrue(all("温度 30.0°C" in payload for payload in payloads))

    def test_now_playing_uses_latest_song_metadata_in_rotation(self) -> None:
        state, manager, client = self.create_manager()
        state.patch("chatbox", batch_enabled=True)
        state.patch(
            "now_playing",
            available=True,
            ready=True,
            playing=True,
            broadcast_enabled=True,
            title="第一首",
            artist="歌手 A",
            player_name="QQ 音乐",
            show_title=True,
            show_artist=True,
            show_album=False,
            show_player=False,
            show_progress=True,
            show_lyrics=True,
            position_seconds=10.0,
            duration_seconds=60.0,
            lyric="当前歌词",
        )
        manager.send_message("old", source="now_playing")
        state.patch("now_playing", title="第二首", artist="歌手 B")

        self.assertTrue(manager.send_next_batch())
        self.assertEqual(
            client.messages[0][1][0],
            "正在播放: ♪ 第二首 | 歌手: 歌手 B\n"
            "0:10 ->----- 1:00\n"
            "歌词: 当前歌词",
        )
        self.assertEqual(state.snapshot()["chatbox"]["last_source"], "now_playing")
        self.assertTrue(state.snapshot()["now_playing"]["last_sent"])


class ChatboxBatchLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_is_resampled_repeatedly_during_one_batch_slot(self) -> None:
        state = RuntimeState()
        state.patch(
            "chatbox",
            batch_enabled=True,
            batch_interval=5.0,
            device_enabled=True,
            device_interval=1.0,
        )
        manager = ChatboxManager(state)
        manager._client._sock.close()
        client = FakeUdpClient()
        manager._client = client
        samples = iter((device_sample(10.0), device_sample(88.0)))

        with patch("vrctool_app.chatbox.get_device_info", side_effect=samples):
            await manager.start()
            try:
                for _ in range(30):
                    if len(client.messages) >= 2:
                        break
                    await asyncio.sleep(0.05)

                self.assertGreaterEqual(len(client.messages), 2)
                self.assertIn("CPU 10.00%", client.messages[0][1][0])
                self.assertIn("CPU 88.00%", client.messages[1][1][0])
                self.assertEqual(
                    state.snapshot()["chatbox"]["batch_current_source"],
                    "device",
                )
            finally:
                await manager.shutdown()

    async def test_heart_rate_updates_repeatedly_during_one_batch_slot(self) -> None:
        state = RuntimeState()
        state.patch("chatbox", batch_enabled=True, batch_interval=5.0)
        state.patch(
            "heart_rate",
            send_enabled=True,
            connected=True,
            interval=1.0,
            bpm=72,
            device_name="Heart Sensor",
        )
        manager = ChatboxManager(state)
        manager._client._sock.close()
        client = FakeUdpClient()
        manager._client = client

        await manager.start()
        try:
            for _ in range(20):
                if client.messages:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(len(client.messages), 1)
            self.assertIn("72 BPM", client.messages[0][1][0])

            state.patch("heart_rate", bpm=99)
            for _ in range(30):
                if len(client.messages) >= 2:
                    break
                await asyncio.sleep(0.05)

            self.assertGreaterEqual(len(client.messages), 2)
            self.assertIn("99 BPM", client.messages[1][1][0])
            self.assertEqual(
                state.snapshot()["chatbox"]["batch_current_source"],
                "heart_rate",
            )
        finally:
            await manager.shutdown()

    async def test_scheduler_switches_only_after_current_slot_ends(self) -> None:
        state = RuntimeState()
        state.patch(
            "chatbox",
            batch_enabled=True,
            batch_interval=1.0,
            custom_enabled=True,
            custom_message="custom",
            custom_interval=3.0,
        )
        state.patch(
            "heart_rate",
            send_enabled=True,
            connected=True,
            interval=1.0,
            bpm=80,
        )
        manager = ChatboxManager(state)
        manager._client._sock.close()
        client = FakeUdpClient()
        manager._client = client

        await manager.start()
        try:
            for _ in range(30):
                if len(client.messages) >= 2:
                    break
                await asyncio.sleep(0.05)

            self.assertGreaterEqual(len(client.messages), 2)
            self.assertEqual(client.messages[0][1][0], "custom")
            self.assertIn("80 BPM", client.messages[1][1][0])
            self.assertEqual(
                state.snapshot()["chatbox"]["batch_current_source"],
                "heart_rate",
            )
        finally:
            await manager.shutdown()

    async def test_scheduler_continuously_sends_a_single_weather_source(self) -> None:
        state = RuntimeState()
        state.patch("chatbox", batch_enabled=True, batch_interval=1.0)
        state.patch(
            "weather",
            broadcast_enabled=True,
            ready=True,
            location_name="上海市",
            condition="晴",
            temperature=30.0,
            feels_like=31.0,
            humidity=60,
            wind_speed=5.0,
            precipitation=0.0,
        )
        manager = ChatboxManager(state)
        manager._client._sock.close()
        client = FakeUdpClient()
        manager._client = client

        await manager.start()
        try:
            for _ in range(30):
                if len(client.messages) >= 2:
                    break
                await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(client.messages), 2)
            self.assertTrue(all("上海市天气" in item[1][0] for item in client.messages))
        finally:
            await manager.shutdown()

    async def test_shutdown_cleans_batch_scheduler_task(self) -> None:
        state = RuntimeState()
        manager = ChatboxManager(state)
        manager._client._sock.close()
        manager._client = FakeUdpClient()

        await manager.start()
        task = manager._batch_task
        self.assertIsNotNone(task)
        self.assertFalse(task.done())

        await asyncio.wait_for(manager.shutdown(), timeout=1.0)

        self.assertIsNone(manager._batch_task)
        self.assertTrue(task.cancelled())


if __name__ == "__main__":
    unittest.main()
