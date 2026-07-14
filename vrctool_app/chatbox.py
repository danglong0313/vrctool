from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from pythonosc.udp_client import SimpleUDPClient

from .device_info import format_device_message, get_device_info
from .state import RuntimeState


BATCH_SOURCE_ORDER = (
    "custom",
    "device",
    "afk",
    "heart_rate",
    "performance",
    "dglab",
)
BATCH_SOURCE_LABELS = {
    "manual": "手动消息",
    "custom": "自定义文字",
    "device": "设备信息",
    "afk": "挂机计时",
    "heart_rate": "心率",
    "performance": "游戏帧率",
    "dglab": "郊狼状态",
}


class ChatboxManager:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state
        self._client: Optional[SimpleUDPClient] = SimpleUDPClient("127.0.0.1", 9000)
        self._device_task: Optional[asyncio.Task] = None
        self._afk_task: Optional[asyncio.Task] = None
        self._custom_task: Optional[asyncio.Task] = None
        self._dglab_task: Optional[asyncio.Task] = None
        self._batch_task: Optional[asyncio.Task] = None
        self._batch_wakeup = asyncio.Event()
        self._batch_messages: dict[str, str] = {}
        self._batch_cursor = 0
        self._afk_started = datetime.now()

    def configure(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        next_client = SimpleUDPClient(host, port)
        previous_client = self._client
        self._client = next_client
        self._close_client(previous_client)
        self.state.patch("chatbox", host=host, port=port)

    @staticmethod
    def _close_client(client: Optional[SimpleUDPClient]) -> None:
        sock = getattr(client, "_sock", None)
        close = getattr(sock, "close", None)
        if callable(close):
            close()

    async def start(self) -> None:
        self.refresh_batch_state()
        if self.state.snapshot()["chatbox"].get("batch_enabled", True):
            self._ensure_batch_task()

    def send_message(self, message: str, source: str = "manual") -> bool:
        message = str(message or "")[:240]
        if not message:
            return False
        if source in BATCH_SOURCE_ORDER:
            active_sources = self._active_sources()
            if source not in active_sources:
                return False
            self._batch_messages[source] = message
            self.refresh_batch_state(active_sources)
            if (
                self.state.snapshot()["chatbox"].get("batch_enabled", True)
                and len(active_sources) > 1
            ):
                self._batch_wakeup.set()
                return False
        self._send_now(message, source)
        return True

    def _send_now(self, message: str, source: str) -> None:
        if self._client is None:
            return
        self._client.send_message("/chatbox/input", [message, True, False])
        self.state.patch(
            "chatbox",
            last_message=message,
            last_source=source,
            batch_current_source=source if source in BATCH_SOURCE_ORDER else "",
        )
        label = BATCH_SOURCE_LABELS.get(source, source)
        self.state.log("ok", f"已发送 ChatBox 消息：{label}")

    async def configure_batch(self, enabled: bool, interval: float = 3.0) -> None:
        interval = max(1.0, min(float(interval), 60.0))
        self.state.patch(
            "chatbox",
            batch_enabled=bool(enabled),
            batch_interval=interval,
        )
        if enabled:
            self._ensure_batch_task()
            self._batch_wakeup.set()
            self.state.log("ok", f"ChatBox 批量轮播已开启，每 {interval:g} 秒发送下一项")
        else:
            await self._stop_batch_task()
            self.state.patch(
                "chatbox",
                batch_running=False,
                batch_current_source="",
                batch_next_source="",
            )
            self.state.log("ok", "ChatBox 批量轮播已关闭")
        self.refresh_batch_state()

    def refresh_batch_state(self, active_sources: Optional[list[str]] = None) -> None:
        active = active_sources if active_sources is not None else self._active_sources()
        enabled = bool(self.state.snapshot()["chatbox"].get("batch_enabled", True))
        next_source = self._next_available_source(active) if enabled and len(active) > 1 else ""
        self.state.patch(
            "chatbox",
            batch_running=enabled and len(active) > 1,
            batch_active_sources=active,
            batch_order=list(BATCH_SOURCE_ORDER),
            batch_next_source=next_source,
        )
        self._batch_wakeup.set()

    def source_changed(self, source: str) -> None:
        if source not in self._active_sources():
            self._batch_messages.pop(source, None)
        self.refresh_batch_state()

    def send_next_batch(self) -> bool:
        chatbox = self.state.snapshot()["chatbox"]
        active = self._active_sources()
        if not chatbox.get("batch_enabled", True) or len(active) < 2:
            self.refresh_batch_state(active)
            return False
        source = self._next_available_source(active)
        if not source:
            self.refresh_batch_state(active)
            return False
        message = self._batch_messages[source]
        self._batch_cursor = (BATCH_SOURCE_ORDER.index(source) + 1) % len(BATCH_SOURCE_ORDER)
        self._send_now(message, source)
        self.refresh_batch_state(active)
        return True

    def _next_available_source(self, active_sources: list[str]) -> str:
        for offset in range(len(BATCH_SOURCE_ORDER)):
            index = (self._batch_cursor + offset) % len(BATCH_SOURCE_ORDER)
            source = BATCH_SOURCE_ORDER[index]
            if source in active_sources and self._batch_messages.get(source):
                return source
        return ""

    def _active_sources(self) -> list[str]:
        snapshot = self.state.snapshot()
        chatbox = snapshot["chatbox"]
        heart_rate = snapshot["heart_rate"]
        performance = snapshot["performance"]
        enabled = {
            "custom": bool(
                chatbox.get("custom_enabled")
                and str(chatbox.get("custom_message") or "").strip()
            ),
            "device": bool(chatbox.get("device_enabled")),
            "afk": bool(chatbox.get("afk_enabled")),
            "heart_rate": bool(
                heart_rate.get("send_enabled")
                and heart_rate.get("connected")
                and int(heart_rate.get("bpm") or 0) > 0
            ),
            "performance": bool(
                performance.get("broadcast_enabled")
                and performance.get("vrchat_running")
                and performance.get("sampling")
            ),
            "dglab": bool(chatbox.get("dglab_enabled")),
        }
        return [source for source in BATCH_SOURCE_ORDER if enabled[source]]

    def _ensure_batch_task(self) -> None:
        if self._batch_task and not self._batch_task.done():
            return
        self._batch_task = asyncio.create_task(
            self._batch_loop(),
            name="vrctool-chatbox-batch",
        )

    async def _stop_batch_task(self) -> None:
        task = self._batch_task
        self._batch_task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _batch_loop(self) -> None:
        while self.state.snapshot()["chatbox"].get("batch_enabled", True):
            active = self._active_sources()
            self.refresh_batch_state(active)
            if len(active) < 2 or not self._next_available_source(active):
                self._batch_wakeup.clear()
                try:
                    await asyncio.wait_for(self._batch_wakeup.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                self.send_next_batch()
            except Exception as exc:
                self.state.log("err", f"ChatBox 批量轮播发送失败：{exc}")
                await asyncio.sleep(1)
                continue
            interval = max(
                1.0,
                float(self.state.snapshot()["chatbox"].get("batch_interval") or 3.0),
            )
            await asyncio.sleep(interval)

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
        self.source_changed("custom")
        self.state.log("ok", f"自定义文本已开启，每 {interval:g} 秒发送一次")

    async def stop_custom_message(self) -> None:
        if self._custom_task:
            self._custom_task.cancel()
            await asyncio.gather(self._custom_task, return_exceptions=True)
            self._custom_task = None
        self.state.patch("chatbox", custom_enabled=False)
        self.source_changed("custom")

    async def _custom_loop(self, interval: float) -> None:
        while True:
            message = self.state.snapshot()["chatbox"].get("custom_message", "")
            if message:
                self.send_message(message[:240], source="custom")
            await asyncio.sleep(interval)

    async def start_device_status(self, interval: float = 3.0) -> None:
        await self.stop_device_status()
        interval = max(1.0, float(interval))
        self.state.patch("chatbox", device_enabled=True, device_interval=interval)
        self._device_task = asyncio.create_task(self._device_loop(interval))
        self.source_changed("device")
        self.state.log("ok", f"设备信息已开启，每 {interval:g} 秒发送一次")

    async def stop_device_status(self) -> None:
        if self._device_task:
            self._device_task.cancel()
            await asyncio.gather(self._device_task, return_exceptions=True)
            self._device_task = None
        self.state.patch("chatbox", device_enabled=False)
        self.source_changed("device")

    async def _device_loop(self, interval: float) -> None:
        while True:
            info = get_device_info()
            self.state.patch("device", **info)
            self.send_message(format_device_message(info), source="device")
            interval = max(
                1.0,
                float(self.state.snapshot()["chatbox"].get("device_interval") or interval),
            )
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
        self.source_changed("afk")
        self.state.log("ok", f"挂机计时已开启，每 {interval:g} 秒发送一次")

    async def stop_afk(self) -> None:
        if self._afk_task:
            self._afk_task.cancel()
            await asyncio.gather(self._afk_task, return_exceptions=True)
            self._afk_task = None
        self.state.patch("chatbox", afk_enabled=False)
        self.source_changed("afk")

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
            self.send_message(message, source="afk")
            interval = max(
                1.0,
                float(self.state.snapshot()["chatbox"].get("afk_interval") or interval),
            )
            await asyncio.sleep(interval)

    async def start_dglab_status(self, interval: float = 1.0) -> None:
        await self.stop_dglab_status()
        interval = max(1.0, float(interval))
        self.state.patch("chatbox", dglab_enabled=True, dglab_interval=interval)
        self._dglab_task = asyncio.create_task(self._dglab_loop(interval))
        self.source_changed("dglab")
        self.state.log("ok", f"郊狼状态已开启，每 {interval:g} 秒发送一次")

    async def stop_dglab_status(self) -> None:
        if self._dglab_task:
            self._dglab_task.cancel()
            await asyncio.gather(self._dglab_task, return_exceptions=True)
            self._dglab_task = None
        self.state.patch("chatbox", dglab_enabled=False)
        self.source_changed("dglab")

    async def _dglab_loop(self, interval: float) -> None:
        while True:
            self.send_message(format_dglab_message(self.state.snapshot()), source="dglab")
            await asyncio.sleep(interval)

    async def shutdown(self) -> None:
        await self.stop_device_status()
        await self.stop_afk()
        await self.stop_custom_message()
        await self.stop_dglab_status()
        await self._stop_batch_task()
        client = self._client
        self._client = None
        self._close_client(client)


def format_dglab_message(snapshot: dict) -> str:
    dglab = snapshot["dglab"]
    osc = snapshot["osc"]
    waveforms = {
        item["value"]: item["label"]
        for item in dglab.get("waveforms", [])
        if "value" in item and "label" in item
    }
    running = "运行中" if dglab["running"] else "已停止"
    bound = "已连接" if dglab["bound"] else "未连接"
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
