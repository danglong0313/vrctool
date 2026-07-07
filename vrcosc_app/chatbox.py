from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from pythonosc.udp_client import SimpleUDPClient

from .device_info import format_device_message, get_device_info
from .state import RuntimeState


class ChatboxManager:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state
        self._client = SimpleUDPClient("127.0.0.1", 9000)
        self._device_task: Optional[asyncio.Task] = None
        self._afk_task: Optional[asyncio.Task] = None
        self._custom_task: Optional[asyncio.Task] = None
        self._dglab_task: Optional[asyncio.Task] = None
        self._afk_started = datetime.now()

    def configure(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        self._client = SimpleUDPClient(host, port)
        self.state.patch("chatbox", host=host, port=port)

    def send_message(self, message: str) -> None:
        self._client.send_message("/chatbox/input", [message, True, False])
        self.state.patch("chatbox", last_message=message)
        self.state.log("ok", "已发送 ChatBox 消息")

    def set_custom_message(self, message: str, interval: float = 3.0) -> None:
        self.state.patch(
            "chatbox",
            custom_interval=max(1.0, float(interval)),
            custom_message=message[:240],
        )

    async def start_custom_message(self, message: str, interval: float = 3.0) -> None:
        await self.stop_custom_message()
        interval = max(1.0, float(interval))
        message = message[:240]
        self.state.patch(
            "chatbox",
            custom_enabled=True,
            custom_interval=interval,
            custom_message=message,
        )
        self._custom_task = asyncio.create_task(self._custom_loop(interval))
        self.state.log("ok", f"自定义文本已开启，每 {interval:g} 秒发送一次")

    async def stop_custom_message(self) -> None:
        if self._custom_task:
            self._custom_task.cancel()
            await asyncio.gather(self._custom_task, return_exceptions=True)
            self._custom_task = None
        self.state.patch("chatbox", custom_enabled=False)

    async def _custom_loop(self, interval: float) -> None:
        while True:
            message = self.state.snapshot()["chatbox"].get("custom_message", "")
            if message:
                self.send_message(message[:240])
            await asyncio.sleep(interval)

    async def start_device_status(self, interval: float = 3.0) -> None:
        await self.stop_device_status()
        interval = max(1.0, float(interval))
        self.state.patch("chatbox", device_enabled=True, device_interval=interval)
        self._device_task = asyncio.create_task(self._device_loop(interval))
        self.state.log("ok", f"设备信息已开启，每 {interval:g} 秒发送一次")

    async def stop_device_status(self) -> None:
        if self._device_task:
            self._device_task.cancel()
            await asyncio.gather(self._device_task, return_exceptions=True)
            self._device_task = None
        self.state.patch("chatbox", device_enabled=False)

    async def _device_loop(self, interval: float) -> None:
        while True:
            info = get_device_info()
            self.state.patch("device", **info)
            self.send_message(format_device_message(info))
            await asyncio.sleep(interval)

    async def start_afk(self, interval: float = 3.0) -> None:
        await self.stop_afk()
        interval = max(1.0, float(interval))
        self._afk_started = datetime.now()
        self.state.patch(
            "afk",
            start_time=self._afk_started.isoformat(timespec="seconds"),
            elapsed_seconds=0,
        )
        self.state.patch("chatbox", afk_enabled=True, afk_interval=interval)
        self._afk_task = asyncio.create_task(self._afk_loop(interval))
        self.state.log("ok", f"挂机计时已开启，每 {interval:g} 秒发送一次")

    async def stop_afk(self) -> None:
        if self._afk_task:
            self._afk_task.cancel()
            await asyncio.gather(self._afk_task, return_exceptions=True)
            self._afk_task = None
        self.state.patch("chatbox", afk_enabled=False)

    def reset_afk(self) -> None:
        self._afk_started = datetime.now()
        self.state.patch(
            "afk",
            start_time=self._afk_started.isoformat(timespec="seconds"),
            elapsed_seconds=0,
        )
        self.state.log("ok", "挂机计时已重置")

    async def _afk_loop(self, interval: float) -> None:
        while True:
            elapsed = int((datetime.now() - self._afk_started).total_seconds())
            self.state.patch("afk", elapsed_seconds=elapsed)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            message = (
                "正在挂机...\n"
                f"开始: {self._afk_started.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"时长: {hours:02d}小时{minutes:02d}分{seconds:02d}秒"
            )
            self.send_message(message)
            await asyncio.sleep(interval)

    async def start_dglab_status(self, interval: float = 1.0) -> None:
        await self.stop_dglab_status()
        interval = max(1.0, float(interval))
        self.state.patch("chatbox", dglab_enabled=True, dglab_interval=interval)
        self._dglab_task = asyncio.create_task(self._dglab_loop(interval))
        self.state.log("ok", f"郊狼状态已开启，每 {interval:g} 秒发送一次")

    async def stop_dglab_status(self) -> None:
        if self._dglab_task:
            self._dglab_task.cancel()
            await asyncio.gather(self._dglab_task, return_exceptions=True)
            self._dglab_task = None
        self.state.patch("chatbox", dglab_enabled=False)

    async def _dglab_loop(self, interval: float) -> None:
        while True:
            self.send_message(format_dglab_message(self.state.snapshot()))
            await asyncio.sleep(interval)

    async def shutdown(self) -> None:
        await self.stop_device_status()
        await self.stop_afk()
        await self.stop_custom_message()
        await self.stop_dglab_status()


def format_dglab_message(snapshot: dict) -> str:
    dglab = snapshot["dglab"]
    osc = snapshot["osc"]
    waveforms = {
        item["value"]: item["label"]
        for item in dglab.get("waveforms", [])
        if "value" in item and "label" in item
    }
    running = "运行中" if dglab["running"] else "已停止"
    bound = "已绑定" if dglab["bound"] else "未绑定"
    osc_state = "运行中" if osc["running"] else "已停止"
    wave_a = waveforms.get(dglab["waveform_a"], dglab["waveform_a"])
    wave_b = waveforms.get(dglab["waveform_b"], dglab["waveform_b"])
    mode_a = "交互" if dglab.get("mode_a") == "interaction" else "面板"
    mode_b = "交互" if dglab.get("mode_b") == "interaction" else "面板"
    return (
        "郊狼状态\n"
        f"服务: {running} | App: {bound}\n"
        f"模式: A {mode_a} B {mode_b} | 当前 {dglab['selected_channel']}\n"
        f"A {dglab['strength_a']}/{dglab['safety_limit_a']} | "
        f"B {dglab['strength_b']}/{dglab['safety_limit_b']}\n"
        f"OSC: {osc_state} | 波形: {wave_a}/{wave_b}"
    )
