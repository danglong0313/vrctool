from __future__ import annotations

from typing import Dict, List, Tuple

from pydglab_ws.utils import PULSE_DATA_MAX_LENGTH

from .pulse_data import PULSE_DATA, PULSE_NAME

PulseOperation = Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]

DEFAULT_WAVEFORM = PULSE_NAME[0]


def options() -> List[Dict[str, str]]:
    return [{"value": name, "label": name} for name in PULSE_NAME]


def get_waveform(name: str) -> List[PulseOperation]:
    return list(PULSE_DATA.get(name) or PULSE_DATA[DEFAULT_WAVEFORM])


def build_waveform_packet(name: str, repeats: int = 6) -> List[PulseOperation]:
    base = get_waveform(name)
    packet = (base * max(1, repeats))[:PULSE_DATA_MAX_LENGTH]
    return packet
