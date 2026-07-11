from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vrctool_app import installation


class InstallationTests(unittest.TestCase):
    def test_find_uninstaller_prefers_latest_default_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "unins000.exe"
            latest = root / "unins001.exe"
            older.write_bytes(b"old")
            latest.write_bytes(b"new")
            os.utime(older, (1, 1))
            os.utime(latest, (2, 2))
            with patch("vrctool_app.installation.app_root", return_value=root):
                found = installation.find_uninstaller()
        self.assertEqual(found, latest)

    def test_launch_uninstaller_stops_running_app_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            uninstaller = Path(temp_dir) / "unins000.exe"
            helper = Path(temp_dir) / "helper.ps1"
            uninstaller.write_bytes(b"test")
            with (
                patch("vrctool_app.installation.find_uninstaller", return_value=uninstaller),
                patch("vrctool_app.installation.stop_running_instance") as stop,
                patch("vrctool_app.installation.powershell_path", return_value=uninstaller),
                patch("vrctool_app.installation.uninstall_helper_path", return_value=helper),
                patch("vrctool_app.installation.subprocess.Popen") as popen,
            ):
                launched = installation.launch_uninstaller()
        stop.assert_called_once_with()
        self.assertEqual(popen.call_args.args[0][-2], "-File")
        self.assertEqual(launched, uninstaller)

    def test_silent_uninstall_passes_inno_setup_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            uninstaller = Path(temp_dir) / "unins000.exe"
            helper = Path(temp_dir) / "helper.ps1"
            uninstaller.write_bytes(b"test")
            with (
                patch("vrctool_app.installation.find_uninstaller", return_value=uninstaller),
                patch("vrctool_app.installation.stop_running_instance"),
                patch("vrctool_app.installation.powershell_path", return_value=uninstaller),
                patch("vrctool_app.installation.uninstall_helper_path", return_value=helper),
                patch("vrctool_app.installation.subprocess.Popen") as popen,
            ):
                installation.launch_uninstaller(silent=True)
            script = helper.read_text(encoding="utf-8-sig")
        command = popen.call_args.args[0]
        self.assertEqual(command[-2], "-File")
        self.assertIn("Start-Sleep -Milliseconds 1500", script)
        self.assertIn("/VERYSILENT", script)
        self.assertIn("/SUPPRESSMSGBOXES", script)


if __name__ == "__main__":
    unittest.main()
