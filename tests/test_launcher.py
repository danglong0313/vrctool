from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from vrctool_app.launcher import (
    main,
    open_browser_when_ready,
    parse_args,
    run_upgrade,
    wait_for_web_ready,
)


class LauncherArgumentTests(unittest.TestCase):
    def test_start_command_accepts_short_port_option(self) -> None:
        args = parse_args(["start", "-p", "8877", "--no-browser"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.port, 8877)
        self.assertTrue(args.no_browser)

    def test_port_option_without_command_only_sets_default_port(self) -> None:
        args = parse_args(["-p", "8878"])
        self.assertEqual(args.command, "setport")
        self.assertEqual(args.port, 8878)

    def test_setport_command_accepts_positional_port(self) -> None:
        args = parse_args(["setport", "8879"])
        self.assertEqual(args.command, "setport")
        self.assertEqual(args.port, 8879)

    def test_start_without_port_uses_configured_port_later(self) -> None:
        args = parse_args(["start"])
        self.assertIsNone(args.port)

    def test_version_command_and_short_option_are_equivalent(self) -> None:
        self.assertEqual(parse_args(["version"]).command, "version")
        self.assertEqual(parse_args(["-v"]).command, "version")

    def test_upgrade_command_and_short_option_are_equivalent(self) -> None:
        self.assertEqual(parse_args(["upgrade"]).command, "upgrade")
        self.assertEqual(parse_args(["-u"]).command, "upgrade")
        self.assertTrue(parse_args(["-u", "--check"]).check)

    def test_setting_port_does_not_start_application(self) -> None:
        with (
            patch("vrctool_app.launcher.is_tcp_port_available", return_value=True),
            patch("vrctool_app.launcher.set_configured_web_port", return_value=8890) as save,
        ):
            result = main(["-p", "8890"])
        self.assertEqual(result, 0)
        save.assert_called_once_with(8890)

    def test_setting_occupied_port_is_rejected(self) -> None:
        with (
            patch("vrctool_app.launcher.read_running_instance", return_value=None),
            patch("vrctool_app.launcher.is_tcp_port_available", return_value=False),
            patch("vrctool_app.launcher.set_configured_web_port") as save,
        ):
            result = main(["setport", "8891"])
        self.assertEqual(result, 1)
        save.assert_not_called()

    def test_upgrade_downloads_and_installs_available_release(self) -> None:
        manager = MagicMock()
        manager.can_install = True
        manager.check_for_updates.return_value = {
            "update": {
                "status": "available",
                "available": True,
                "current_version": "2.3.2",
                "latest_version": "2.3.3",
            }
        }
        with patch("vrctool_app.launcher.UpdateManager", return_value=manager):
            result = run_upgrade()
        self.assertEqual(result, 0)
        manager.download_update_blocking.assert_called_once_with()
        manager.install_update.assert_called_once_with()

    def test_invalid_port_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["-p", "70000"])

    def test_web_readiness_retries_until_status_endpoint_responds(self) -> None:
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with (
            patch(
                "vrctool_app.launcher.urlopen",
                side_effect=[URLError("not ready"), response],
            ) as request,
            patch("vrctool_app.launcher.time.sleep"),
        ):
            ready = wait_for_web_ready("http://127.0.0.1:8765", timeout=1.0)

        self.assertTrue(ready)
        self.assertEqual(request.call_count, 2)
        request.assert_called_with("http://127.0.0.1:8765/api/status", timeout=1.0)

    def test_browser_opens_only_after_web_service_is_ready(self) -> None:
        with (
            patch("vrctool_app.launcher.wait_for_web_ready", return_value=True) as wait,
            patch("vrctool_app.launcher.webbrowser.open") as browser_open,
        ):
            opened = open_browser_when_ready("http://127.0.0.1:8765")

        self.assertTrue(opened)
        wait.assert_called_once_with("http://127.0.0.1:8765", timeout=60.0)
        browser_open.assert_called_once_with("http://127.0.0.1:8765")

    def test_browser_is_not_opened_when_web_service_never_becomes_ready(self) -> None:
        with (
            patch("vrctool_app.launcher.wait_for_web_ready", return_value=False),
            patch("vrctool_app.launcher.webbrowser.open") as browser_open,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            opened = open_browser_when_ready("http://127.0.0.1:8765")

        self.assertFalse(opened)
        browser_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
