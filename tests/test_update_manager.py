from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vrctool_app.state import RuntimeState
from vrctool_app.update_manager import (
    UpdateError,
    UpdateManager,
    extract_version,
    normalize_sha256,
    select_installer_asset,
)


class StubUpdateManager(UpdateManager):
    def __init__(self, state: RuntimeState, release) -> None:
        self.release = release
        super().__init__(state)

    def _fetch_json(self, _url):
        return self.release


class UpdateManagerTests(unittest.TestCase):
    def test_extract_version_supports_old_and_new_tag_formats(self) -> None:
        self.assertEqual(str(extract_version("vrctool_v2.1")), "2.1")
        self.assertEqual(str(extract_version("v2.3.1")), "2.3.1")

    def test_select_installer_asset_prefers_vrctool_setup(self) -> None:
        selected = select_installer_asset(
            {
                "assets": [
                    {"name": "helper-setup.exe"},
                    {"name": "release-notes-2.3.1.txt"},
                    {"name": "vrctool-setup-2.3.1.exe"},
                ]
            }
        )
        self.assertEqual(selected["name"], "vrctool-setup-2.3.1.exe")

    def test_normalize_sha256_requires_a_complete_digest(self) -> None:
        digest = "a" * 64
        self.assertEqual(normalize_sha256(f"sha256:{digest}"), digest)
        with self.assertRaises(UpdateError):
            normalize_sha256("sha256:1234")

    def test_check_for_updates_exposes_release_asset(self) -> None:
        digest = "b" * 64
        state = RuntimeState()
        manager = StubUpdateManager(
            state,
            {
                "tag_name": "v99.0.0",
                "name": "vrctool 99",
                "body": "release notes",
                "html_url": "https://github.com/danglong0313/vrctool/releases/tag/v99.0.0",
                "assets": [
                    {
                        "name": "vrctool-setup-99.0.0.exe",
                        "size": 1024,
                        "browser_download_url": "https://github.com/example.exe",
                        "digest": f"sha256:{digest}",
                    }
                ],
            },
        )

        update = manager.check_for_updates()["update"]

        self.assertEqual(update["status"], "available")
        self.assertTrue(update["available"])
        self.assertEqual(update["asset_name"], "vrctool-setup-99.0.0.exe")
        self.assertEqual(update["digest"], digest)

    def test_install_update_starts_waiter_before_current_process_exits(self) -> None:
        digest = "c" * 64
        state = RuntimeState()
        manager = UpdateManager(state)
        manager.can_install = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            powershell = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            powershell.parent.mkdir(parents=True)
            powershell.write_bytes(b"test")
            installer = root / "vrctool-setup-99.0.0.exe"
            helper = root / "update-helper.ps1"
            installer.write_bytes(b"installer")
            state.patch(
                "update",
                status="ready",
                can_install=True,
                installer_path=str(installer),
                digest=digest,
            )

            with (
                patch.dict(os.environ, {"SystemRoot": str(root)}),
                patch("vrctool_app.update_manager.file_sha256", return_value=digest),
                patch("vrctool_app.update_manager.update_helper_path", return_value=helper),
                patch("vrctool_app.update_manager.subprocess.Popen") as popen,
            ):
                result = manager.install_update()
            script = helper.read_text(encoding="utf-8-sig")

        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(powershell))
        self.assertEqual(command[-2], "-File")
        self.assertIn(str(os.getpid()), script)
        self.assertIn("Start-Sleep -Milliseconds 1500", script)
        self.assertIn("/VERYSILENT", script)
        self.assertEqual(result["update"]["status"], "installing")


if __name__ == "__main__":
    unittest.main()
