from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from typing import Dict, Optional

import qrcode
from pydglab_ws import (
    Channel,
    DGLabWSServer,
    RetCode,
    StrengthData,
    StrengthOperationType,
)

from .state import RuntimeState
from .waveforms import build_waveform_packet, options


CHANNELS = {"A": Channel.A, "B": Channel.B}


def _qr_data_url(text: str) -> str:
    image = qrcode.make(text)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class DGLabManager:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state
        self.server: Optional[DGLabWSServer] = None
        self.client = None
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._running = False
        self._fire_origin = {"A": 0, "B": 0}
        self.state.patch("dglab", waveforms=options())

    async def start(self, listen_host: str, advertise_host: str, port: int) -> Dict[str, str]:
        async with self._lock:
            await self._stop_unlocked()
            self.server = DGLabWSServer(listen_host, port, heartbeat_interval=10)
            self.client = self.server.new_local_client()
            self.server.add_connection_callback("new_connect", self._on_connect)
            self.server.add_connection_callback("disconnect", self._on_disconnect)
            await self.server.__aenter__()

            self._running = True
            uri = f"ws://{advertise_host}:{port}"
            qr_text = self.client.get_qrcode(uri)
            qr_image = _qr_data_url(qr_text) if qr_text else ""

            self.state.patch(
                "dglab",
                running=True,
                bound=False,
                listen_host=listen_host,
                advertise_host=advertise_host,
                port=port,
                qr_text=qr_text or "",
                qr_image=qr_image,
                client_id=str(self.client.client_id),
                target_id="",
                app_connections=0,
            )
            self._tasks = [
                asyncio.create_task(self._data_loop()),
                asyncio.create_task(self._pulse_loop()),
            ]
            self.state.log("ok", f"DG-LAB WebSocket 已启动：{uri}")
            return {"qr_text": qr_text or "", "qr_image": qr_image}

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        if self.client and self.client.target_id:
            await self._zero_strength(clear_pulses=True)

        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        if self.server and self.client:
            try:
                await self.server.remove_local_client(self.client.client_id)
            except Exception:
                pass
        if self.server:
            try:
                await self.server.__aexit__(None, None, None)
            except Exception:
                pass

        self.server = None
        self.client = None
        self.state.patch(
            "dglab",
            running=False,
            bound=False,
            qr_text="",
            qr_image="",
            client_id="",
            target_id="",
            app_connections=0,
            strength_a=0,
            strength_b=0,
        )

    def _on_connect(self, _uuid, _websocket) -> None:
        snapshot = self.state.snapshot()["dglab"]
        self.state.patch("dglab", app_connections=int(snapshot["app_connections"]) + 1)
        self.state.log("info", "DG-LAB App 已连接 WebSocket，等待设备连接")

    def _on_disconnect(self, _uuid, _websocket) -> None:
        snapshot = self.state.snapshot()["dglab"]
        self.state.patch("dglab", app_connections=max(0, int(snapshot["app_connections"]) - 1))
        self.state.log("warn", "DG-LAB App WebSocket 已断开")

    def _is_bound(self) -> bool:
        return bool(self.client and not self.client.not_bind)

    async def _data_loop(self) -> None:
        while self._running and self.client:
            try:
                if self.client.not_bind:
                    self.state.patch("dglab", bound=False, target_id="")
                    code = await self.client.bind()
                    if code == RetCode.SUCCESS:
                        self.state.patch(
                            "dglab",
                            bound=True,
                            target_id=str(self.client.target_id),
                        )
                        self.state.log("ok", "DG-LAB App 连接成功")
                else:
                    data = await self.client.recv_data()
                    if isinstance(data, StrengthData):
                        snapshot = self.state.snapshot()["dglab"]
                        self.state.patch(
                            "dglab",
                            strength_a=data.a,
                            strength_b=data.b,
                            limit_a=data.a_limit,
                            limit_b=data.b_limit,
                            safety_limit_a=min(int(snapshot["safety_limit_a"]), data.a_limit),
                            safety_limit_b=min(int(snapshot["safety_limit_b"]), data.b_limit),
                        )
                    elif data == RetCode.CLIENT_DISCONNECTED:
                        self.client._target_id = None
                        self.state.patch("dglab", bound=False, target_id="")
                        self.state.log("warn", "DG-LAB App 已断开连接")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.log("err", f"DG-LAB 数据循环异常：{exc}")
                await asyncio.sleep(1)

    async def _pulse_loop(self) -> None:
        while self._running:
            try:
                dglab = self.state.snapshot()["dglab"]
                if dglab["pulse_enabled"] and self._is_bound():
                    await self._send_waveform("A")
                    await asyncio.sleep(0.1)
                    await self._send_waveform("B")
                await asyncio.sleep(2.8)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.log("err", f"持续输出波形异常：{exc}")
                await asyncio.sleep(1)

    async def _send_waveform(self, channel_name: str) -> None:
        if not self._is_bound():
            return
        dglab = self.state.snapshot()["dglab"]
        waveform = dglab["waveform_a"] if channel_name == "A" else dglab["waveform_b"]
        channel = CHANNELS[channel_name]
        data = build_waveform_packet(waveform, repeats=6)
        await self.client.clear_pulses(channel)
        await self.client.add_pulses(channel, *data)

    async def set_strength(self, channel_name: str, value: int, source: str = "web") -> Dict[str, object]:
        channel_name = channel_name.upper()
        if channel_name not in CHANNELS:
            return {"ok": False, "error": "unknown_channel"}
        return await self._set_strength_value(channel_name, value, source)

    async def _set_strength_value(self, channel_name: str, value: int, source: str) -> Dict[str, object]:
        if not self._is_bound():
            if source != "OSC":
                self.state.log("warn", "DG-LAB 尚未连接，强度未下发")
            return {"ok": False, "error": "dglab_not_bound"}

        dglab = self.state.snapshot()["dglab"]
        safety_key = "safety_limit_a" if channel_name == "A" else "safety_limit_b"
        device_limit_key = "limit_a" if channel_name == "A" else "limit_b"
        max_allowed = min(int(dglab[safety_key]), int(dglab[device_limit_key]))
        value = max(0, min(int(value), max_allowed))
        await self.client.set_strength(CHANNELS[channel_name], StrengthOperationType.SET_TO, value)
        patch_key = "strength_a" if channel_name == "A" else "strength_b"
        self.state.patch("dglab", **{patch_key: value})
        self.state.log("info", f"{source} 设置 {channel_name} 通道强度为 {value}")
        return {"ok": True, "strength": value}

    def set_channel_mode(self, channel_name: str, mode: str) -> None:
        channel_name = channel_name.upper()
        mode = "panel" if mode == "panel" else "interaction"
        if channel_name == "A":
            self.state.patch("dglab", mode_a=mode)
        elif channel_name == "B":
            self.state.patch("dglab", mode_b=mode)
        else:
            return
        label = "交互" if mode == "interaction" else "面板"
        self.state.log("ok", f"{channel_name} 通道已切换为{label}模式")

    def toggle_selected_channel_mode(self) -> None:
        dglab = self.state.snapshot()["dglab"]
        channel_name = dglab["selected_channel"]
        key = "mode_a" if channel_name == "A" else "mode_b"
        next_mode = "panel" if dglab[key] == "interaction" else "interaction"
        self.set_channel_mode(channel_name, next_mode)

    def set_panel_channel_from_page(self, value: float) -> None:
        selected = "A" if float(value) <= 1 else "B"
        self.state.patch("dglab", selected_channel=selected)

    def set_panel_control(self, value: float) -> None:
        enabled = bool(value)
        self.state.patch("dglab", panel_enabled=enabled, panel_control=value)
        self.state.log("ok", "VRChat 面板控制已开启" if enabled else "VRChat 面板控制已关闭")

    def set_panel_settings(self, fire_step: int, adjust_step: int, panel_enabled: bool) -> None:
        self.state.patch(
            "dglab",
            fire_step=max(0, min(int(fire_step), 200)),
            adjust_step=max(1, min(int(adjust_step), 100)),
            panel_enabled=bool(panel_enabled),
        )
        self.state.log("ok", "VRChat 面板参数已更新")

    def set_fire_step(self, fire_step: int) -> None:
        self.state.patch("dglab", fire_step=max(0, min(int(fire_step), 200)))

    def set_fire_step_from_volume(self, value: float) -> None:
        fire_step = max(0, min(int(float(value) * 100), 200))
        self.state.patch("dglab", fire_step=fire_step)

    async def adjust_selected_strength(self, delta: int, source: str = "面板") -> Dict[str, object]:
        dglab = self.state.snapshot()["dglab"]
        channel_name = dglab["selected_channel"]
        current_key = "strength_a" if channel_name == "A" else "strength_b"
        target = int(dglab[current_key]) + int(delta)
        return await self._set_strength_value(channel_name, target, source)

    async def reset_selected_strength(self) -> Dict[str, object]:
        channel_name = self.state.snapshot()["dglab"]["selected_channel"]
        return await self._set_strength_value(channel_name, 0, "面板归零")

    async def set_selected_waveform_by_index(self, index: int) -> None:
        dglab = self.state.snapshot()["dglab"]
        waveforms = dglab.get("waveforms", [])
        if index < 0 or index >= len(waveforms):
            return
        await self.set_waveform(dglab["selected_channel"], waveforms[index]["value"])

    async def set_fire_active(self, active: bool) -> Dict[str, object]:
        dglab = self.state.snapshot()["dglab"]
        channel_name = dglab["selected_channel"]
        current_key = "strength_a" if channel_name == "A" else "strength_b"
        if active:
            self._fire_origin[channel_name] = int(dglab[current_key])
            self.state.patch("dglab", fire_active=True)
            target = int(dglab[current_key]) + int(dglab["fire_step"])
            return await self._set_strength_value(channel_name, target, "面板开火")

        self.state.patch("dglab", fire_active=False)
        return await self._set_strength_value(channel_name, self._fire_origin[channel_name], "面板开火结束")

    def interaction_allowed(self, channel_name: str) -> bool:
        dglab = self.state.snapshot()["dglab"]
        key = "mode_a" if channel_name.upper() == "A" else "mode_b"
        return dglab.get(key) == "interaction"

    async def set_waveform(self, channel_name: str, waveform: str) -> None:
        channel_name = channel_name.upper()
        if channel_name == "A":
            self.state.patch("dglab", waveform_a=waveform)
        elif channel_name == "B":
            self.state.patch("dglab", waveform_b=waveform)
        else:
            return
        if self.state.snapshot()["dglab"]["pulse_enabled"]:
            await self._send_waveform(channel_name)
        self.state.log("ok", f"{channel_name} 通道波形已切换")

    async def set_pulse_enabled(self, enabled: bool) -> None:
        self.state.patch("dglab", pulse_enabled=enabled)
        if not self._is_bound():
            return
        if enabled:
            await self._send_waveform("A")
            await self._send_waveform("B")
            self.state.log("ok", "持续输出波形已开启")
        else:
            await self.client.clear_pulses(Channel.A)
            await self.client.clear_pulses(Channel.B)
            self.state.log("warn", "持续输出波形已关闭")

    async def emergency_stop(self) -> None:
        await self._zero_strength(clear_pulses=True)
        self.state.log("warn", "已执行紧急归零")

    async def _zero_strength(self, clear_pulses: bool = False) -> None:
        if not self._is_bound():
            self.state.patch("dglab", strength_a=0, strength_b=0)
            return
        await self.client.set_strength(Channel.A, StrengthOperationType.SET_TO, 0)
        await self.client.set_strength(Channel.B, StrengthOperationType.SET_TO, 0)
        if clear_pulses:
            await self.client.clear_pulses(Channel.A)
            await self.client.clear_pulses(Channel.B)
        self.state.patch("dglab", strength_a=0, strength_b=0)

    def set_safety_limits(self, a: int, b: int) -> None:
        dglab = self.state.snapshot()["dglab"]
        max_a = int(dglab.get("limit_a") or 0)
        max_b = int(dglab.get("limit_b") or 0)
        self.state.patch(
            "dglab",
            safety_limit_a=max(0, min(int(a), max_a)),
            safety_limit_b=max(0, min(int(b), max_b)),
        )
        self.state.log("ok", "强度上限已更新")
