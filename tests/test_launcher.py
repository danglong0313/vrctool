from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from vrctool_app.launcher import main, parse_args, run_upgrade


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


if __name__ == "__main__":
    unittest.main()
