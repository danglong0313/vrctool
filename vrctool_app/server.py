from __future__ import annotations

import asyncio
import threading
from uuid import uuid4
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vrctool_app.chatbox import ChatboxManager
from vrctool_app.config_store import load_config, save_config
from vrctool_app.device_info import get_device_info
from vrctool_app.dglab import DGLabManager
from vrctool_app.heartrate import HeartRateManager
from vrctool_app.lifecycle import request_shutdown
from vrctool_app.network import get_network_interfaces, pick_default_lan_ip
from vrctool_app.osc import VRChatOSCManager
from vrctool_app.performance import PerformanceManager
from vrctool_app.state import RuntimeState
from vrctool_app.update_manager import UpdateError, UpdateManager

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
ASSETS_DIR = PACKAGE_DIR / "assets"

app = FastAPI(title="vrctool")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

state = RuntimeState()
config = load_config()
for config_section in ("chatbox", "dglab", "heart_rate", "performance", "osc"):
    state.patch(config_section, **config.get(config_section, {}))
updates = UpdateManager(state)
chatbox = ChatboxManager(state)
heart_rate = HeartRateManager(
    state,
    lambda message: chatbox.send_message(message, source="heart_rate"),
)
performance = PerformanceManager(
    state,
    lambda message: chatbox.send_message(message, source="performance"),
)
dglab = DGLabManager(state)
vrchat_osc = VRChatOSCManager(state, dglab, chatbox)


@app.middleware("http")
async def disable_ui_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path == "/logo.png" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def update_config(section: str, **values) -> None:
    config.setdefault(section, {}).update(values)
    save_config(config)


class ChatboxConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 9000


class ChatboxBatchPayload(BaseModel):
    enabled: bool = True
    interval: float = 3.0


class MessagePayload(BaseModel):
    message: str


class TogglePayload(BaseModel):
    enabled: bool
    interval: float = 3.0


class CustomTextPayload(BaseModel):
    enabled: bool
    message: str = ""
    interval: float = 3.0


class DGLabStartPayload(BaseModel):
    listen_host: str = "0.0.0.0"
    advertise_host: Optional[str] = None
    port: int = 5678


class StrengthPayload(BaseModel):
    channel: str
    value: int


class WaveformPayload(BaseModel):
    channel: str
    waveform: str


class PulsePayload(BaseModel):
    enabled: bool


class LimitsPayload(BaseModel):
    a: int
    b: int


class ModePayload(BaseModel):
    channel: str
    mode: str


class PanelSettingsPayload(BaseModel):
    fire_step: int = 30
    adjust_step: int = 5
    panel_enabled: bool = True


class FireStepPayload(BaseModel):
    fire_step: int


class HeartRateScanPayload(BaseModel):
    timeout: float = 5.0


class HeartRateConnectPayload(BaseModel):
    address: str
    name: str = ""


class HeartRateChatboxPayload(BaseModel):
    enabled: bool
    interval: float = 1.0


class PerformanceConfigPayload(BaseModel):
    enabled: bool = False
    interval: float = 3.0
    low_fps_threshold: float = 45.0
    show_avg_fps: bool = False
    show_frame_ms: bool = True


class OSCStartPayload(BaseModel):
    host: str = "127.0.0.1"
    port: int = 9001


class OSCConfigPayload(BaseModel):
    enabled: bool = True
    address_a: str = "/avatar/parameters/DG-LAB/UpperLeg_L"
    address_b: str = "/avatar/parameters/DG-LAB/UpperLeg_R"
    channel_a: str = "A"
    channel_b: str = "B"
    threshold: float = 0.02


class CustomOSCPayload(BaseModel):
    address: str
    channel: str = "A"
    enabled: bool = True


class CustomOSCRemovePayload(BaseModel):
    mapping_id: str


class CustomOSCUpdatePayload(BaseModel):
    mapping_id: str
    enabled: bool


@app.on_event("startup")
async def startup() -> None:
    state.patch("device", **get_device_info())
    chatbox_config = state.snapshot()["chatbox"]
    chatbox.configure(chatbox_config["host"], chatbox_config["port"])
    await chatbox.start()
    await performance.start()
    chatbox.refresh_batch_state()
    try:
        osc_config = state.snapshot()["osc"]
        if osc_config.get("enabled", True):
            vrchat_osc.start(osc_config["listen_host"], int(osc_config["listen_port"]))
    except Exception as exc:
        state.log("warn", f"OSC 自动启动失败：{exc}")

    try:
        advertise_host = pick_default_lan_ip()
        dglab_config = state.snapshot()["dglab"]
        await dglab.start("0.0.0.0", advertise_host, int(dglab_config["port"]))
    except Exception as exc:
        state.log("warn", f"DG-LAB 自动启动失败：{exc}")

    if updates.can_install:
        asyncio.create_task(asyncio.to_thread(updates.check_for_updates))


@app.on_event("shutdown")
async def shutdown() -> None:
    vrchat_osc.stop()
    await performance.shutdown()
    await heart_rate.shutdown()
    await chatbox.shutdown()
    await dglab.stop()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/logo.png")
async def logo() -> FileResponse:
    return FileResponse(ASSETS_DIR / "logo.png", media_type="image/png")


@app.get("/api/status")
async def get_status():
    return state.snapshot()


@app.get("/api/network")
async def network():
    return {"interfaces": get_network_interfaces(), "default_ip": pick_default_lan_ip()}


@app.post("/api/device/refresh")
async def refresh_device():
    state.patch("device", **get_device_info())
    state.log("ok", "设备信息已刷新")
    return state.snapshot()


@app.post("/api/app/shutdown")
async def shutdown_app():
    ok = request_shutdown()
    state.log("warn", "正在关闭后端服务" if ok else "当前启动方式不支持网页关闭")
    return {"ok": ok}


@app.get("/api/update/check")
async def check_update():
    return await asyncio.to_thread(updates.check_for_updates)


@app.post("/api/update/download")
async def download_update():
    try:
        return updates.start_download()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/update/install")
async def install_update():
    try:
        snapshot = updates.install_update()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    timer = threading.Timer(1.0, lambda: request_shutdown())
    timer.daemon = True
    timer.start()
    return snapshot


@app.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(state.snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


@app.post("/api/chatbox/config")
async def configure_chatbox(payload: ChatboxConfig):
    chatbox.configure(payload.host, payload.port)
    update_config("chatbox", host=payload.host, port=payload.port)
    return state.snapshot()


@app.post("/api/chatbox/send")
async def send_chatbox(payload: MessagePayload):
    chatbox.send_message(payload.message[:240])
    return state.snapshot()


@app.post("/api/chatbox/batch")
async def configure_chatbox_batch(payload: ChatboxBatchPayload):
    await chatbox.configure_batch(payload.enabled, payload.interval)
    snapshot = state.snapshot()["chatbox"]
    update_config(
        "chatbox",
        batch_enabled=snapshot["batch_enabled"],
        batch_interval=snapshot["batch_interval"],
    )
    return state.snapshot()


@app.post("/api/chatbox/custom")
async def toggle_custom_chatbox(payload: CustomTextPayload):
    interval = max(1.0, float(payload.interval))
    message = payload.message[:240]
    update_config("chatbox", custom_message=message, custom_interval=interval)
    if payload.enabled:
        if state.snapshot()["chatbox"].get("custom_enabled"):
            chatbox.set_custom_message(message, interval)
        else:
            await chatbox.start_custom_message(message, interval)
    else:
        await chatbox.stop_custom_message()
        state.patch("chatbox", custom_message=message, custom_interval=interval)
    return state.snapshot()


@app.post("/api/chatbox/device")
async def toggle_device(payload: TogglePayload):
    interval = max(1.0, float(payload.interval))
    if payload.enabled:
        await chatbox.start_device_status(interval)
    else:
        await chatbox.stop_device_status()
        state.patch("chatbox", device_interval=interval)
    update_config("chatbox", device_interval=interval)
    return state.snapshot()


@app.post("/api/chatbox/afk")
async def toggle_afk(payload: TogglePayload):
    interval = max(1.0, float(payload.interval))
    if payload.enabled:
        await chatbox.start_afk(interval)
    else:
        await chatbox.stop_afk()
        state.patch("chatbox", afk_interval=interval)
    update_config("chatbox", afk_interval=interval)
    return state.snapshot()


@app.post("/api/chatbox/afk/reset")
async def reset_afk():
    chatbox.reset_afk()
    return state.snapshot()


@app.post("/api/chatbox/dglab")
async def toggle_dglab_status(payload: TogglePayload):
    if payload.enabled:
        await chatbox.start_dglab_status(payload.interval or 1.0)
    else:
        await chatbox.stop_dglab_status()
    return state.snapshot()


@app.post("/api/dglab/start")
async def start_dglab(payload: DGLabStartPayload):
    advertise_host = payload.advertise_host or pick_default_lan_ip()
    await dglab.start(payload.listen_host, advertise_host, payload.port)
    update_config("dglab", port=payload.port)
    return state.snapshot()


@app.post("/api/dglab/stop")
async def stop_dglab():
    await dglab.stop()
    return state.snapshot()


@app.post("/api/dglab/strength")
async def set_strength(payload: StrengthPayload):
    result = await dglab.set_strength(payload.channel, payload.value, source="网页")
    snapshot = state.snapshot()
    snapshot["result"] = result
    return snapshot


@app.post("/api/dglab/waveform")
async def set_waveform(payload: WaveformPayload):
    await dglab.set_waveform(payload.channel, payload.waveform)
    key = "waveform_a" if payload.channel.upper() == "A" else "waveform_b"
    update_config("dglab", **{key: payload.waveform})
    return state.snapshot()


@app.post("/api/dglab/pulse")
async def set_pulse(payload: PulsePayload):
    await dglab.set_pulse_enabled(payload.enabled)
    update_config("dglab", pulse_enabled=payload.enabled)
    return state.snapshot()


@app.post("/api/dglab/limits")
async def set_limits(payload: LimitsPayload):
    dglab.set_safety_limits(payload.a, payload.b)
    snapshot = state.snapshot()["dglab"]
    update_config(
        "dglab",
        safety_limit_a=snapshot["safety_limit_a"],
        safety_limit_b=snapshot["safety_limit_b"],
    )
    return state.snapshot()


@app.post("/api/dglab/mode")
async def set_mode(payload: ModePayload):
    dglab.set_channel_mode(payload.channel, payload.mode)
    key = "mode_a" if payload.channel.upper() == "A" else "mode_b"
    update_config("dglab", **{key: state.snapshot()["dglab"][key]})
    return state.snapshot()


@app.post("/api/dglab/panel-settings")
async def set_panel_settings(payload: PanelSettingsPayload):
    dglab.set_panel_settings(payload.fire_step, payload.adjust_step, payload.panel_enabled)
    snapshot = state.snapshot()["dglab"]
    update_config(
        "dglab",
        fire_step=snapshot["fire_step"],
        adjust_step=snapshot["adjust_step"],
        panel_enabled=snapshot["panel_enabled"],
    )
    return state.snapshot()


@app.post("/api/dglab/fire-step")
async def set_fire_step(payload: FireStepPayload):
    dglab.set_fire_step(payload.fire_step)
    update_config("dglab", fire_step=state.snapshot()["dglab"]["fire_step"])
    return state.snapshot()


@app.post("/api/dglab/emergency-stop")
async def emergency_stop():
    await dglab.emergency_stop()
    return state.snapshot()


@app.post("/api/heartrate/scan")
async def scan_heart_rate(payload: HeartRateScanPayload):
    await heart_rate.scan(payload.timeout)
    return state.snapshot()


@app.post("/api/heartrate/connect")
async def connect_heart_rate(payload: HeartRateConnectPayload):
    await heart_rate.connect(payload.address, payload.name)
    snapshot = state.snapshot()["heart_rate"]
    update_config(
        "heart_rate",
        address=snapshot["address"],
        device_name=snapshot["device_name"],
        interval=snapshot["interval"],
    )
    return state.snapshot()


@app.post("/api/heartrate/disconnect")
async def disconnect_heart_rate():
    await heart_rate.disconnect()
    return state.snapshot()


@app.post("/api/heartrate/chatbox")
async def toggle_heart_rate_chatbox(payload: HeartRateChatboxPayload):
    interval = max(1.0, float(payload.interval))
    if payload.enabled:
        await heart_rate.start_chatbox(interval)
    else:
        await heart_rate.stop_chatbox()
        state.patch("heart_rate", interval=interval)
    chatbox.source_changed("heart_rate")
    update_config("heart_rate", interval=state.snapshot()["heart_rate"]["interval"])
    return state.snapshot()


@app.post("/api/performance/config")
async def configure_performance(payload: PerformanceConfigPayload):
    await performance.configure(
        payload.enabled,
        payload.interval,
        payload.low_fps_threshold,
        payload.show_avg_fps,
        payload.show_frame_ms,
    )
    chatbox.source_changed("performance")
    snapshot = state.snapshot()["performance"]
    update_config(
        "performance",
        broadcast_enabled=snapshot["broadcast_enabled"],
        interval=snapshot["interval"],
        low_fps_threshold=snapshot["low_fps_threshold"],
        show_avg_fps=snapshot["show_avg_fps"],
        show_frame_ms=snapshot["show_frame_ms"],
    )
    return state.snapshot()


@app.post("/api/performance/grant-capture")
async def grant_performance_capture():
    result = await performance.request_capture_permission()
    snapshot = state.snapshot()
    snapshot["result"] = result
    return snapshot


@app.post("/api/osc/start")
async def start_osc(payload: OSCStartPayload):
    vrchat_osc.start(payload.host, payload.port)
    update_config("osc", listen_host=payload.host, listen_port=payload.port, enabled=True)
    return state.snapshot()


@app.post("/api/osc/stop")
async def stop_osc():
    vrchat_osc.stop()
    update_config("osc", enabled=False)
    return state.snapshot()


@app.post("/api/osc/config")
async def configure_osc(payload: OSCConfigPayload):
    vrchat_osc.configure(
        payload.enabled,
        payload.address_a,
        payload.address_b,
        payload.threshold,
        payload.channel_a,
        payload.channel_b,
    )
    update_config(
        "osc",
        enabled=payload.enabled,
        address_a=payload.address_a,
        address_b=payload.address_b,
        channel_a=state.snapshot()["osc"]["channel_a"],
        channel_b=state.snapshot()["osc"]["channel_b"],
        threshold=state.snapshot()["osc"]["threshold"],
    )
    return state.snapshot()


@app.post("/api/osc/custom")
async def add_custom_osc(payload: CustomOSCPayload):
    address = payload.address.strip()
    if not address.startswith("/"):
        address = f"/{address}"
    channel = payload.channel.upper()
    if channel not in {"A", "B", "A+B", "AB", "BOTH"}:
        channel = "A"
    if channel in {"AB", "BOTH"}:
        channel = "A+B"
    mapping = {
        "id": str(uuid4()),
        "address": address,
        "channel": channel,
        "enabled": bool(payload.enabled),
    }
    snapshot = state.snapshot()["osc"]
    custom_mappings = list(snapshot.get("custom_mappings", []))
    custom_mappings.append(mapping)
    vrchat_osc.configure(
        snapshot["enabled"],
        snapshot["address_a"],
        snapshot["address_b"],
        snapshot["threshold"],
        channel_a=snapshot.get("channel_a", "A"),
        channel_b=snapshot.get("channel_b", "B"),
        custom_mappings=custom_mappings,
    )
    update_config("osc", custom_mappings=custom_mappings)
    return state.snapshot()


@app.post("/api/osc/custom/remove")
async def remove_custom_osc(payload: CustomOSCRemovePayload):
    custom_mappings = [
        item
        for item in state.snapshot()["osc"].get("custom_mappings", [])
        if item.get("id") != payload.mapping_id
    ]
    snapshot = state.snapshot()["osc"]
    vrchat_osc.configure(
        snapshot["enabled"],
        snapshot["address_a"],
        snapshot["address_b"],
        snapshot["threshold"],
        channel_a=snapshot.get("channel_a", "A"),
        channel_b=snapshot.get("channel_b", "B"),
        custom_mappings=custom_mappings,
    )
    update_config("osc", custom_mappings=custom_mappings)
    return state.snapshot()


@app.post("/api/osc/custom/update")
async def update_custom_osc(payload: CustomOSCUpdatePayload):
    snapshot = state.snapshot()["osc"]
    custom_mappings = []
    for item in snapshot.get("custom_mappings", []):
        mapping = dict(item)
        if mapping.get("id") == payload.mapping_id:
            mapping["enabled"] = bool(payload.enabled)
        custom_mappings.append(mapping)
    vrchat_osc.configure(
        snapshot["enabled"],
        snapshot["address_a"],
        snapshot["address_b"],
        snapshot["threshold"],
        channel_a=snapshot.get("channel_a", "A"),
        channel_b=snapshot.get("channel_b", "B"),
        custom_mappings=custom_mappings,
    )
    update_config("osc", custom_mappings=custom_mappings)
    return state.snapshot()
