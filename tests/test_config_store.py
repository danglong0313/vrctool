from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vrctool_app import config_store


class ConfigStoreTests(unittest.TestCase):
    def test_frozen_app_migrates_legacy_config_to_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "portable"
            local_app_data = root / "local"
            legacy_root.mkdir()
            (legacy_root / "config.json").write_text(
                json.dumps({"chatbox": {"port": 9012}}),
                encoding="utf-8",
            )

            with (
                patch.object(sys, "frozen", True, create=True),
                patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}),
                patch("vrctool_app.config_store.app_root", return_value=legacy_root),
            ):
                loaded = config_store.load_config()
                migrated_path = local_app_data / "vrctool" / "config.json"

            self.assertEqual(loaded["chatbox"]["port"], 9012)
            self.assertTrue(migrated_path.is_file())
            migrated = json.loads(migrated_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["chatbox"]["port"], 9012)


if __name__ == "__main__":
    unittest.main()
