from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "chatbox": {
        "host": "127.0.0.1",
        "port": 9000,
        "device_interval": 3.0,
        "afk_interval": 3.0,
        "custom_interval": 3.0,
        "custom_message": "",
    },
    "dglab": {
        "port": 5678,
        "safety_limit_a": 60,
        "safety_limit_b": 60,
        "mode_a": "interaction",
        "mode_b": "interaction",
        "panel_enabled": True,
        "fire_step": 30,
        "adjust_step": 5,
        "pulse_enabled": True,
        "waveform_a": "呼吸",
        "waveform_b": "呼吸",
    },
    "heart_rate": {
        "address": "",
        "device_name": "",
        "interval": 1.0,
    },
    "osc": {
        "listen_host": "127.0.0.1",
        "listen_port": 9001,
        "enabled": True,
        "address_a": "/avatar/parameters/DG-LAB/UpperLeg_L",
        "address_b": "/avatar/parameters/DG-LAB/UpperLeg_R",
        "channel_a": "A",
        "channel_b": "B",
        "threshold": 0.02,
        "custom_mappings": [],
    }
}


def config_path() -> Path:
    return Path(sys.argv[0]).resolve().parent / "config.json"


def load_config() -> Dict[str, Any]:
    path = config_path()
    config = deepcopy(DEFAULT_CONFIG)
    if not path.exists():
        return config
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config
    if isinstance(loaded, dict):
        for section, values in loaded.items():
            if isinstance(values, dict) and isinstance(config.get(section), dict):
                config[section].update(values)
            else:
                config[section] = values
    return config


def save_config(config: Dict[str, Any]) -> None:
    path = config_path()
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
