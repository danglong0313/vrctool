from __future__ import annotations

import unittest

from vrctool_app.chatbox import ChatboxManager
from vrctool_app.state import RuntimeState


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

    def test_single_enabled_source_keeps_its_original_immediate_send(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
        )

        sent = manager.send_message("custom", source="custom")

        self.assertTrue(sent)
        self.assertEqual(client.messages[0][1][0], "custom")

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

        self.assertTrue(manager.send_next_batch())
        self.assertTrue(manager.send_next_batch())
        self.assertTrue(manager.send_next_batch())

        payloads = [message[1][0] for message in client.messages]
        self.assertEqual(payloads, ["custom", "device", "custom"])
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

        manager.send_next_batch()
        manager.send_next_batch()
        manager.send_next_batch()

        self.assertEqual(
            [item[1][0] for item in client.messages],
            ["custom", "device", "custom"],
        )

    def test_weather_remains_in_round_robin_after_its_batch_turn(self) -> None:
        state, manager, client = self.create_manager()
        state.patch(
            "chatbox",
            batch_enabled=True,
            custom_enabled=True,
            custom_message="custom",
        )
        state.patch("weather", broadcast_enabled=True, ready=True)
        manager.send_message("custom", source="custom")
        manager.send_message("weather", source="weather")

        for _ in range(6):
            manager.send_next_batch()

        payloads = [item[1][0] for item in client.messages]
        self.assertEqual(payloads, ["custom", "weather"] * 3)
        self.assertEqual(manager._batch_messages["weather"], "weather")


class ChatboxBatchLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cleans_batch_scheduler_task(self) -> None:
        state = RuntimeState()
        manager = ChatboxManager(state)
        manager._client._sock.close()
        manager._client = FakeUdpClient()

        await manager.start()
        task = manager._batch_task
        self.assertIsNotNone(task)
        self.assertFalse(task.done())

        await manager.shutdown()

        self.assertIsNone(manager._batch_task)
        self.assertTrue(task.cancelled())


if __name__ == "__main__":
    unittest.main()
