from __future__ import annotations

import contextlib
import io
import unittest

from vrctool_app.launcher import parse_args


class LauncherArgumentTests(unittest.TestCase):
    def test_start_command_accepts_short_port_option(self) -> None:
        args = parse_args(["start", "-p", "8877", "--no-browser"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.port, 8877)
        self.assertTrue(args.no_browser)

    def test_port_option_without_command_starts_application(self) -> None:
        args = parse_args(["-p", "8878"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.port, 8878)

    def test_version_command_and_short_option_are_equivalent(self) -> None:
        self.assertEqual(parse_args(["version"]).command, "version")
        self.assertEqual(parse_args(["-v"]).command, "version")

    def test_invalid_port_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["-p", "70000"])


if __name__ == "__main__":
    unittest.main()
