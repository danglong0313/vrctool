from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from typing import Optional

from pythonosc import dispatcher, osc_server

from .chatbox import ChatboxManager
from .dglab import DGLabManager
from .state import RuntimeState


class VRChatOSCManager:
    def __init__(self, state: RuntimeState, dglab: DGLabManager, chatbox: ChatboxManager | None = None) -> None:
        self.state = state
        self.dglab = dglab
        self.chatbox = chatbox
        self._server: Optional[osc_server.ThreadingOSCUDPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_send = {"A": 0.0, "B": 0.0}

    def start(self, host: str = "127.0.0.1", port: int = 9001) -> None:
        self.stop()
        self._loop = asyncio.get_running_loop()
        disp = dispatcher.Dispatcher()
        disp.set_default_handler(self._handle_message)
        self._server = osc_server.ThreadingOSCUDPServer((host, int(port)), disp)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.state.patch("osc", running=True, listen_host=host, listen_port=int(port))
        self.state.log("ok", f"VRChat OSC 监听已启动：{host}:{port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.state.patch("osc", running=False)

    def configure(
        self,
        enabled: bool,
        address_a: str,
        address_b: str,
        threshold: float,
        channel_a: str | None = None,
        channel_b: str | None = None,
        custom_mappings: list[dict[str, Any]] | None = None,
    ) -> None:
        values = {
            "enabled": bool(enabled),
            "address_a": address_a,
            "address_b": address_b,
            "threshold": max(0.0, min(float(threshold), 0.95)),
        }
        if channel_a is not None:
            values["channel_a"] = self._normalize_channel(channel_a)
        if channel_b is not None:
            values["channel_b"] = self._normalize_channel(channel_b)
        if custom_mappings is not None:
            values["custom_mappings"] = custom_mappings
        self.state.patch(
            "osc",
            **values,
        )
        self.state.log("ok", "OSC 映射已更新")

    def _handle_message(self, address: str, *args) -> None:
        snapshot = self.state.snapshot()
        osc = snapshot["osc"]
        if not args:
            value = 0.0
        else:
            raw = args[0]
            if isinstance(raw, bool):
                value = 1.0 if raw else 0.0
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    value = 0.0

        channels: list[str] = []
        for address_key, channel_key in (("address_a", "channel_a"), ("address_b", "channel_b")):
            if address == osc.get(address_key):
                channels.extend(self._expand_channel(osc.get(channel_key, "A")))
        for mapping in osc.get("custom_mappings", []):
            if not mapping.get("enabled", True) or mapping.get("address") != address:
                continue
            channels.extend(self._expand_channel(mapping.get("channel", "A")))
        channels = list(dict.fromkeys(channels))

        self.state.patch(
            "osc",
            last_address=address,
            last_value=value,
            last_channel="+".join(channels),
        )
        if address.startswith("/avatar/parameters/SoundPad/"):
            if self._loop:
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_panel_message(address, value),
                    self._loop,
                )
                future.add_done_callback(self._log_future_error)
            return

        if not osc["enabled"] or not channels:
            return

        now = time.monotonic()
        threshold = float(osc["threshold"])
        normalized = 0.0 if value <= threshold else (value - threshold) / (1.0 - threshold)
        normalized = max(0.0, min(normalized, 1.0))
        dglab = snapshot["dglab"]
        last_strength = 0
        for channel in channels:
            if not self.dglab.interaction_allowed(channel):
                continue
            if now - self._last_send[channel] < 0.06:
                continue
            self._last_send[channel] = now
            limit = int(dglab["safety_limit_a"] if channel == "A" else dglab["safety_limit_b"])
            strength = int(normalized * limit)
            last_strength = max(last_strength, strength)

            if self._loop:
                future = asyncio.run_coroutine_threadsafe(
                    self.dglab.set_strength(channel, strength, source="OSC"),
                    self._loop,
                )
                future.add_done_callback(self._log_future_error)
        self.state.patch("osc", last_strength=last_strength)

    async def _handle_panel_message(self, address: str, value: float) -> None:
        dglab = self.state.snapshot()["dglab"]
        if address == "/avatar/parameters/SoundPad/PanelControl":
            self.dglab.set_panel_control(value)
            return
        if not dglab.get("panel_enabled", True):
            return

        if address == "/avatar/parameters/SoundPad/Page":
            self.dglab.set_panel_channel_from_page(value)
        elif address == "/avatar/parameters/SoundPad/Volume":
            self.dglab.set_fire_step_from_volume(value)
        elif address == "/avatar/parameters/SoundPad/Button/1" and value:
            self.dglab.toggle_selected_channel_mode()
        elif address == "/avatar/parameters/SoundPad/Button/2" and value:
            await self.dglab.reset_selected_strength()
        elif address == "/avatar/parameters/SoundPad/Button/3" and value:
            await self.dglab.adjust_selected_strength(-int(dglab["adjust_step"]))
        elif address == "/avatar/parameters/SoundPad/Button/4" and value:
            await self.dglab.adjust_selected_strength(int(dglab["adjust_step"]))
        elif address == "/avatar/parameters/SoundPad/Button/5":
            await self.dglab.set_fire_active(bool(value))
        elif address == "/avatar/parameters/SoundPad/Button/6" and value:
            await self._toggle_dglab_chatbox()
        elif address.startswith("/avatar/parameters/SoundPad/Button/") and value:
            try:
                button_num = int(address.rsplit("/", 1)[-1])
            except ValueError:
                return
            if 7 <= button_num <= 22:
                await self.dglab.set_selected_waveform_by_index(button_num - 7)

    async def _toggle_dglab_chatbox(self) -> None:
        if self.chatbox is None:
            return
        enabled = bool(self.state.snapshot()["chatbox"]["dglab_enabled"])
        if enabled:
            await self.chatbox.stop_dglab_status()
        else:
            await self.chatbox.start_dglab_status(1.0)

    def _log_future_error(self, future) -> None:
        try:
            result = future.result()
            if isinstance(result, dict) and not result.get("ok", True):
                if result.get("error") != "dglab_not_bound":
                    self.state.log("warn", f"OSC 下发失败：{result.get('error')}")
        except Exception as exc:
            self.state.log("err", f"OSC 下发异常：{exc}")

    @staticmethod
    def _normalize_channel(channel: Any) -> str:
        value = str(channel or "A").upper()
        if value in {"AB", "A+B", "BOTH"}:
            return "A+B"
        if value in {"A", "B"}:
            return value
        return "A"

    @classmethod
    def _expand_channel(cls, channel: Any) -> list[str]:
        value = cls._normalize_channel(channel)
        if value == "A+B":
            return ["A", "B"]
        return [value]
