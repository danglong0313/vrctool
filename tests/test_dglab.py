from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4

from websockets import connect

from vrctool_app.dglab import DGLabManager, ResilientDGLabWSServer
from vrctool_app.state import RuntimeState


class ResilientDGLabServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_websocket_reconnects_keep_heartbeat_running(self) -> None:
        server = ResilientDGLabWSServer(
            "127.0.0.1",
            0,
            heartbeat_interval=0.01,
            ping_interval=None,
        )
        await server.__aenter__()
        try:
            port = server._serve.ws_server.sockets[0].getsockname()[1]
            for _ in range(5):
                async with connect(f"ws://127.0.0.1:{port}") as websocket:
                    await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    await asyncio.sleep(0.02)
                await asyncio.sleep(0.01)

            self.assertIsNotNone(server._heartbeat_task)
            self.assertFalse(server._heartbeat_task.done())
        finally:
            await server.__aexit__(None, None, None)

    async def test_heartbeat_survives_connection_removal_during_send(self) -> None:
        server = ResilientDGLabWSServer("127.0.0.1", 0, heartbeat_interval=10)
        first_id = uuid4()
        second_id = uuid4()
        first_socket = object()
        second_socket = object()
        server._uuid_to_ws = {
            first_id: first_socket,
            second_id: second_socket,
        }
        sent = []

        async def send(_message, websocket, **_kwargs) -> None:
            sent.append(websocket)
            server._uuid_to_ws.pop(second_id, None)

        server._send = send

        await server._send_heartbeat_cycle()

        self.assertEqual(sent, [first_socket])

    async def test_heartbeat_continues_after_one_socket_send_fails(self) -> None:
        server = ResilientDGLabWSServer("127.0.0.1", 0, heartbeat_interval=10)
        first_socket = object()
        second_socket = object()
        server._uuid_to_ws = {
            uuid4(): first_socket,
            uuid4(): second_socket,
        }
        sent = []

        async def send(_message, websocket, **_kwargs) -> None:
            sent.append(websocket)
            if websocket is first_socket:
                raise ConnectionError("socket closed")

        server._send = send

        await server._send_heartbeat_cycle()

        self.assertEqual(sent, [first_socket, second_socket])

    async def test_server_exit_awaits_cancelled_heartbeat_task(self) -> None:
        server = ResilientDGLabWSServer("127.0.0.1", 0, heartbeat_interval=10)
        stopped = asyncio.Event()

        async def heartbeat() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        class FakeServe:
            def __init__(self) -> None:
                self.exited = False

            async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
                self.exited = True

        task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        fake_serve = FakeServe()
        server._heartbeat_task = task
        server._serve = fake_serve

        await server.__aexit__(None, None, None)

        self.assertTrue(task.cancelled())
        self.assertTrue(stopped.is_set())
        self.assertTrue(fake_serve.exited)
        self.assertIsNone(server._heartbeat_task)


class DGLabConnectionStateTests(unittest.TestCase):
    def test_disconnect_count_does_not_accumulate_and_target_is_cleared(self) -> None:
        state = RuntimeState()
        manager = DGLabManager(state)
        target_id = uuid4()
        extra_id = uuid4()
        manager.client = SimpleNamespace(target_id=target_id, _target_id=target_id)
        state.patch(
            "dglab",
            bound=True,
            target_id=str(target_id),
            strength_a=30,
            strength_b=20,
            fire_active=True,
        )

        manager._on_connect(target_id, object())
        manager._on_connect(target_id, object())
        manager._on_connect(extra_id, object())
        self.assertEqual(state.snapshot()["dglab"]["app_connections"], 2)

        manager._on_disconnect(extra_id, object())
        self.assertTrue(state.snapshot()["dglab"]["bound"])
        manager._on_disconnect(target_id, object())
        dglab = state.snapshot()["dglab"]

        self.assertEqual(dglab["app_connections"], 0)
        self.assertFalse(dglab["bound"])
        self.assertEqual(dglab["target_id"], "")
        self.assertEqual(dglab["strength_a"], 0)
        self.assertEqual(dglab["strength_b"], 0)
        self.assertIsNone(manager.client._target_id)


if __name__ == "__main__":
    unittest.main()
