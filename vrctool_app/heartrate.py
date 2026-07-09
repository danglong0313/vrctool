from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Any, Callable, Optional

from .state import RuntimeState

HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class HeartRateManager:
    def __init__(self, state: RuntimeState, send_message: Callable[[str], None]) -> None:
        self.state = state
        self.send_message = send_message
        self._client: Any = None
        self._send_task: Optional[asyncio.Task] = None

    async def scan(self, timeout: float = 5.0) -> None:
        bleak = self._load_bleak()
        if bleak is None:
            return
        timeout = max(2.0, min(float(timeout), 15.0))
        self.state.patch("heart_rate", scanning=True, status="扫描中", error="")
        try:
            devices = await self._discover_devices(bleak["scanner"], timeout)
            self.state.patch("heart_rate", devices=devices, scanning=False, status="扫描完成")
            self.state.log("ok", f"心率设备扫描完成：{len(devices)} 个设备")
        except Exception as exc:
            self.state.patch("heart_rate", scanning=False, status="扫描失败", error=str(exc))
            self.state.log("err", f"心率设备扫描失败：{exc}")

    async def connect(self, address: str, name: str = "") -> None:
        bleak = self._load_bleak()
        if bleak is None:
            return
        address = address.strip()
        if not address:
            self.state.log("warn", "请选择心率设备")
            return
        await self.disconnect()
        self.state.patch(
            "heart_rate",
            address=address,
            device_name=name,
            connecting=True,
            connected=False,
            status="连接中",
            error="",
        )
        try:
            client = bleak["client"](address, disconnected_callback=self._on_disconnect)
            await client.connect()
            await client.start_notify(HEART_RATE_MEASUREMENT_UUID, self._on_measurement)
            self._client = client
            self.state.patch(
                "heart_rate",
                connecting=False,
                connected=True,
                status="已连接",
                device_name=name or address,
            )
            self.state.log("ok", f"心率设备已连接：{name or address}")
        except Exception as exc:
            self._client = None
            self.state.patch("heart_rate", connecting=False, connected=False, status="连接失败", error=str(exc))
            self.state.log("err", f"心率设备连接失败：{exc}")

    async def disconnect(self) -> None:
        await self.stop_chatbox()
        client = self._client
        self._client = None
        if client is not None:
            try:
                if getattr(client, "is_connected", False):
                    await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)
                    await client.disconnect()
            except Exception as exc:
                self.state.log("warn", f"心率设备断开时出错：{exc}")
        self.state.patch("heart_rate", connected=False, connecting=False, status="未连接")

    async def start_chatbox(self, interval: float = 1.0) -> None:
        await self.stop_chatbox()
        interval = max(1.0, float(interval))
        self.state.patch("heart_rate", send_enabled=True, interval=interval)
        self._send_task = asyncio.create_task(self._send_loop(interval))
        self.state.log("ok", f"心率 ChatBox 广播已开启，每 {interval:g} 秒发送一次")

    async def stop_chatbox(self) -> None:
        if self._send_task:
            self._send_task.cancel()
            await asyncio.gather(self._send_task, return_exceptions=True)
            self._send_task = None
        self.state.patch("heart_rate", send_enabled=False)

    async def shutdown(self) -> None:
        await self.disconnect()

    async def _send_loop(self, interval: float) -> None:
        while True:
            snapshot = self.state.snapshot()["heart_rate"]
            bpm = int(snapshot.get("bpm") or 0)
            if bpm > 0:
                self.send_message(format_heart_rate_message(snapshot))
            await asyncio.sleep(interval)

    def _on_measurement(self, _sender: Any, data: bytearray) -> None:
        bpm = parse_heart_rate(data)
        if bpm <= 0:
            return
        self.state.patch(
            "heart_rate",
            bpm=bpm,
            last_seen=datetime.now().strftime("%H:%M:%S"),
            status="接收中",
            error="",
        )

    def _on_disconnect(self, _client: Any) -> None:
        self._client = None
        self.state.patch("heart_rate", connected=False, connecting=False, status="已断开")
        self.state.log("warn", "心率设备已断开")

    def _load_bleak(self) -> dict[str, Any] | None:
        try:
            if sys.platform == "win32":
                from bleak.backends.winrt.util import uninitialize_sta

                uninitialize_sta()
            from bleak import BleakClient, BleakScanner
        except Exception as exc:
            self.state.patch("heart_rate", status="缺少蓝牙库", error=str(exc))
            self.state.log("err", "缺少 bleak 依赖，无法读取心率广播")
            return None
        return {"client": BleakClient, "scanner": BleakScanner}

    async def _discover_devices(self, scanner: Any, timeout: float) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []
        try:
            results = await scanner.discover(timeout=timeout, return_adv=True)
            values = results.values()
            for device, advertisement in values:
                discovered.append(device_to_dict(device, advertisement))
        except TypeError:
            devices = await scanner.discover(timeout=timeout)
            for device in devices:
                discovered.append(device_to_dict(device, None))

        unique: dict[str, dict[str, Any]] = {}
        for device in discovered:
            if device["address"]:
                unique[device["address"]] = device
        return sorted(
            unique.values(),
            key=lambda item: (not item["heart_rate_supported"], item["name"].lower(), item["address"]),
        )


def parse_heart_rate(data: bytearray) -> int:
    if len(data) < 2:
        return 0
    flags = data[0]
    if flags & 0x01:
        if len(data) < 3:
            return 0
        return int.from_bytes(data[1:3], byteorder="little", signed=False)
    return int(data[1])


def device_to_dict(device: Any, advertisement: Any) -> dict[str, Any]:
    services = [str(item).lower() for item in getattr(advertisement, "service_uuids", []) or []]
    name = (
        getattr(advertisement, "local_name", None)
        or getattr(device, "name", None)
        or "未知设备"
    )
    rssi = getattr(advertisement, "rssi", None)
    if rssi is None:
        rssi = getattr(device, "rssi", None)
    heart_rate_supported = HEART_RATE_SERVICE_UUID in services or "heart" in name.lower()
    return {
        "address": getattr(device, "address", ""),
        "name": name,
        "rssi": rssi,
        "heart_rate_supported": heart_rate_supported,
    }


def format_heart_rate_message(snapshot: dict[str, Any]) -> str:
    bpm = int(snapshot.get("bpm") or 0)
    name = str(snapshot.get("device_name") or "").strip()
    if name:
        return f"心率: {bpm} BPM\n设备: {name}"
    return f"心率: {bpm} BPM"
