from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi import HTTPException

from vrctool_app import server


class BasicSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_config = deepcopy(server.config)
        snapshot = server.state.snapshot()
        self.original_app = snapshot["app"]
        self.original_chatbox = snapshot["chatbox"]

    def tearDown(self) -> None:
        server.config.clear()
        server.config.update(self.original_config)
        server.state.patch("app", **self.original_app)
        server.state.patch("chatbox", **self.original_chatbox)

    async def test_web_port_is_saved_for_next_start_without_changing_current_port(self) -> None:
        server.state.patch("app", web_host="127.0.0.1", web_port=8765)
        payload = server.BasicSettingsPayload(
            web_port=8877,
            chatbox_host="127.0.0.1",
            chatbox_port=9000,
            device_interval=4,
            afk_interval=5,
        )
        with (
            patch("vrctool_app.server.is_tcp_port_available", return_value=True),
            patch.object(server.chatbox, "configure") as configure_chatbox,
            patch("vrctool_app.server.save_config") as save,
        ):
            result = await server.configure_basic_settings(payload)

        self.assertEqual(result["app"]["web_port"], 8765)
        self.assertEqual(result["app"]["configured_web_port"], 8877)
        self.assertTrue(result["app"]["restart_required"])
        self.assertEqual(server.config["app"]["web_port"], 8877)
        configure_chatbox.assert_called_once_with("127.0.0.1", 9000)
        save.assert_called_once_with(server.config)

    async def test_occupied_web_port_is_rejected(self) -> None:
        server.state.patch("app", web_host="127.0.0.1", web_port=8765)
        payload = server.BasicSettingsPayload(web_port=8877)
        with (
            patch("vrctool_app.server.is_tcp_port_available", return_value=False),
            patch("vrctool_app.server.save_config") as save,
        ):
            with self.assertRaises(HTTPException) as raised:
                await server.configure_basic_settings(payload)

        self.assertEqual(raised.exception.status_code, 409)
        save.assert_not_called()

    async def test_dismissing_release_notes_persists_current_version(self) -> None:
        notes_version = server.state.snapshot()["app"]["release_notes"]["version"]
        with patch("vrctool_app.server.save_config") as save:
            result = await server.configure_release_notes_preference(
                server.ReleaseNotesPreferencePayload(dismissed=True)
            )

        self.assertEqual(result["app"]["dismissed_release_notes_version"], notes_version)
        self.assertFalse(result["app"]["show_release_notes"])
        self.assertEqual(
            server.config["app"]["dismissed_release_notes_version"],
            notes_version,
        )
        save.assert_called_once_with(server.config)


if __name__ == "__main__":
    unittest.main()
