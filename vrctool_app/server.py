from __future__ import annotations

import asyncio
import os
import threading
from uuid import uuid4
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vrctool_app.chatbox import ChatboxManager
from vrctool_app.config_store import get_configured_web_port, load_config, save_config
from vrctool_app.device_info import get_device_info
from vrctool_app.dglab import DGLabManager
from vrctool_app.heartrate import HeartRateManager
from vrctool_app.lifecycle import request_shutdown
from vrctool_app.network import get_network_interfaces, is_tcp_port_available, pick_default_lan_ip
from vrctool_app.now_playing import NowPlayingManager
from vrctool_app.osc import VRChatOSCManager
from vrctool_app.performance import PerformanceManager
from vrctool_app.release_notes import current_release_notes, should_show_release_notes
from vrctool_app.state import RuntimeState
from vrctool_app.update_manager import UpdateError, UpdateManager
from vrctool_app.weather import WeatherError, WeatherManager

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
ASSETS_DIR = PACKAGE_DIR / "assets"

app = FastAPI(title="vrctool")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

state = RuntimeState()
config = load_config()
for config_section in (
    "chatbox",
    "dglab",
    "heart_rate",
    "performance",
    "now_playing",
    "weather",
    "osc",
):
    state.patch(config_section, **config.get(config_section, {}))
configured_web_port = get_configured_web_port(config)
try:
    effective_web_port = int(os.environ.get("VRCTOOL_WEB_PORT", configured_web_port))
except ValueError:
    effective_web_port = configured_web_port
effective_web_host = os.environ.get("VRCTOOL_WEB_HOST", "127.0.0.1")
temporary_web_port = os.environ.get("VRCTOOL_WEB_PORT_TEMPORARY") == "1"
release_notes = current_release_notes()
dismissed_release_notes_version = str(
    config.get("app", {}).get("dismissed_release_notes_version", "")
)
state.patch(
    "app",
    web_host=effective_web_host,
    web_port=effective_web_port,
    configured_web_port=configured_web_port,
    port_temporary=temporary_web_port,
    restart_required=effective_web_port != configured_web_port,
    release_notes=release_notes,
    show_release_notes=should_show_release_notes(
        str(release_notes.get("version") or ""),
        dismissed_release_notes_version,
    ),
    dismissed_release_notes_version=dismissed_release_notes_version,
)
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
now_playing = NowPlayingManager(
    state,
    lambda message: chatbox.send_message(message, source="now_playing"),
    source_changed=lambda: chatbox.source_changed("now_playing"),
)
weather = WeatherManager(
    state,
    lambda message: chatbox.send_message(message, source="weather"),
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


class BasicSettingsPayload(BaseModel):
    web_port: int = Field(default=8765, ge=1, le=65535)
    chatbox_host: str = "127.0.0.1"
    chatbox_port: int = Field(default=9000, ge=1, le=65535)
    device_interval: float = Field(default=3.0, ge=1.0, le=3600.0)
    afk_interval: float = Field(default=3.0, ge=1.0, le=3600.0)


class ReleaseNotesPreferencePayload(BaseModel):
    dismissed: bool = True


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


class NowPlayingConfigPayload(BaseModel):
    enabled: bool = False
    interval: float = Field(default=5.0, ge=1.0, le=60.0)
    preferred_player: str = "auto"
    show_title: bool = True
    show_artist: bool = True
    show_album: bool = False
    show_player: bool = False
    show_progress: bool = True


class WeatherConfigPayload(BaseModel):
    enabled: bool = False
    interval: float = 600.0


class WeatherLocationPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None


class WeatherCityPayload(BaseModel):
    city: str


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
    await weather.start()
    await performance.start()
    await now_playing.start()
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
    await now_playing.shutdown()
    await performance.shutdown()
    await weather.shutdown()
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


@app.post("/api/app/settings")
async def configure_basic_settings(payload: BasicSettingsPayload):
    chatbox_host = payload.chatbox_host.strip() or "127.0.0.1"
    app_snapshot = state.snapshot()["app"]
    current_port = int(app_snapshot["web_port"])
    web_host = str(app_snapshot.get("web_host") or "127.0.0.1")
    if int(payload.web_port) != current_port and not is_tcp_port_available(
        web_host,
        int(payload.web_port),
    ):
        raise HTTPException(status_code=409, detail=f"网页端口 {payload.web_port} 已被占用")
    chatbox.configure(chatbox_host, payload.chatbox_port)
    state.patch(
        "chatbox",
        device_interval=float(payload.device_interval),
        afk_interval=float(payload.afk_interval),
    )
    config.setdefault("app", {})["web_port"] = int(payload.web_port)
    config.setdefault("chatbox", {}).update(
        host=chatbox_host,
        port=int(payload.chatbox_port),
        device_interval=float(payload.device_interval),
        afk_interval=float(payload.afk_interval),
    )
    save_config(config)
    state.patch(
        "app",
        configured_web_port=int(payload.web_port),
        port_temporary=bool(app_snapshot.get("port_temporary"))
        and current_port != int(payload.web_port),
        restart_required=current_port != int(payload.web_port),
    )
    state.log(
        "ok",
        "基础设置已保存，网页端口将在下次启动时生效"
        if current_port != int(payload.web_port)
        else "基础设置已保存",
    )
    return state.snapshot()


@app.post("/api/app/release-notes")
async def configure_release_notes_preference(payload: ReleaseNotesPreferencePayload):
    app_snapshot = state.snapshot()["app"]
    notes_version = str(app_snapshot.get("release_notes", {}).get("version") or "")
    dismissed_version = notes_version if payload.dismissed else ""
    config.setdefault("app", {})["dismissed_release_notes_version"] = dismissed_version
    save_config(config)
    state.patch(
        "app",
        dismissed_release_notes_version=dismissed_version,
        show_release_notes=not payload.dismissed,
    )
    state.log(
        "ok",
        f"v{notes_version} 更新内容提醒已关闭"
        if payload.dismissed
        else "更新内容提醒已恢复",
    )
    return state.snapshot()


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


@app.post("/api/now-playing/config")
async def configure_now_playing(payload: NowPlayingConfigPayload):
    try:
        await now_playing.configure(
            payload.enabled,
            payload.interval,
            payload.preferred_player,
            payload.show_title,
            payload.show_artist,
            payload.show_album,
            payload.show_player,
            payload.show_progress,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    snapshot = state.snapshot()["now_playing"]
    now_playing_config = config.setdefault("now_playing", {})
    now_playing_config.pop("template", None)
    now_playing_config.update(
        broadcast_enabled=snapshot["broadcast_enabled"],
        interval=snapshot["interval"],
        preferred_player=snapshot["preferred_player"],
        show_title=snapshot["show_title"],
        show_artist=snapshot["show_artist"],
        show_album=snapshot["show_album"],
        show_player=snapshot["show_player"],
        show_progress=snapshot["show_progress"],
    )
    save_config(config)
    chatbox.source_changed("now_playing")
    return state.snapshot()


@app.post("/api/now-playing/refresh")
async def refresh_now_playing():
    await now_playing.refresh()
    chatbox.source_changed("now_playing")
    return state.snapshot()


@app.post("/api/weather/config")
async def configure_weather(payload: WeatherConfigPayload):
    await weather.configure(payload.enabled, payload.interval)
    snapshot = state.snapshot()["weather"]
    update_config(
        "weather",
        broadcast_enabled=snapshot["broadcast_enabled"],
        interval=snapshot["interval"],
    )
    chatbox.source_changed("weather")
    return state.snapshot()


@app.post("/api/weather/location")
async def set_weather_location(payload: WeatherLocationPayload):
    if not await weather.use_browser_location(
        payload.latitude,
        payload.longitude,
        payload.accuracy,
    ):
        raise HTTPException(status_code=502, detail=state.snapshot()["weather"]["error"])
    chatbox.source_changed("weather")
    return state.snapshot()


@app.post("/api/weather/auto-location")
async def auto_locate_weather():
    if not await weather.use_ip_location():
        raise HTTPException(status_code=502, detail=state.snapshot()["weather"]["error"])
    chatbox.source_changed("weather")
    return state.snapshot()


@app.post("/api/weather/city")
async def set_weather_city(payload: WeatherCityPayload):
    try:
        success = await weather.search_city(payload.city)
    except WeatherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=502, detail=state.snapshot()["weather"]["error"])
    chatbox.source_changed("weather")
    return state.snapshot()


@app.post("/api/weather/refresh")
async def refresh_weather():
    if not await weather.refresh(auto_locate=False):
        raise HTTPException(status_code=502, detail=state.snapshot()["weather"]["error"])
    chatbox.source_changed("weather")
    return state.snapshot()


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
