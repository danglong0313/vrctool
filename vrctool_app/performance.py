from __future__ import annotations

import asyncio
import csv
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Iterable, Optional

import psutil

from vrctool_app.state import RuntimeState


DEFAULT_INTERVAL = 3.0
DEFAULT_LOW_FPS_THRESHOLD = 45.0
PRESENTMON_VERSION = "2.4.1"
AVERAGE_WINDOW_SECONDS = 5.0
CURRENT_WINDOW_SECONDS = 1.0
SWAP_CHAIN_RECENCY_SECONDS = 0.5
SAMPLE_STALE_SECONDS = 3.0
PROCESS_POLL_SECONDS = 1.0
RETRY_SECONDS = 5.0
MAX_FRAME_TIME_MS = 10_000.0
# A single fixed ETW session name (not per-PID): each capture reclaims it via
# --stop_existing_session, so a session orphaned by a hard-killed PresentMon
# self-heals on the next start instead of piling up and starving ETW.
PERFORMANCE_SESSION_NAME = "vrctool-performance"

# One-time elevation that adds the current user to the built-in "Performance Log
# Users" group (SID S-1-5-32-559) so PresentMon can open ETW sessions without
# vrctool itself running as administrator. Written to a temp .ps1 and launched
# elevated via a single UAC prompt.
_GRANT_SCRIPT_TEMPLATE = (
    '$ErrorActionPreference = "Stop"\n'
    'try {\n'
    '    Add-LocalGroupMember -SID "S-1-5-32-559" -Member \'__MEMBER__\' -ErrorAction Stop\n'
    '} catch {\n'
    '    if ($_.FullyQualifiedErrorId -notlike "MemberExists*") { throw }\n'
    '}\n'
    'exit 0\n'
)

_GRANT_OUTER_TEMPLATE = (
    "try {"
    " $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden"
    " -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','__SCRIPT__';"
    " exit $p.ExitCode"
    "} catch { exit 1223 }"
)


@dataclass(frozen=True)
class ProcessTarget:
    pid: int
    name: str = "VRChat.exe"
    create_time: float = 0.0


@dataclass(frozen=True)
class PresentSample:
    process_id: int
    swap_chain: str
    frame_ms: float
    application: str = ""
    present_time: Optional[float] = None
    dropped: bool = False


@dataclass(frozen=True)
class FrameMetrics:
    fps: float
    avg_fps: float
    frame_ms: float
    swap_chain: str
    sample_count: int


def find_vrchat_process(processes: Optional[Iterable[Any]] = None) -> Optional[ProcessTarget]:
    if processes is None:
        processes = psutil.process_iter(("pid", "name", "create_time"))
    matches: list[ProcessTarget] = []
    for process in processes:
        try:
            info = getattr(process, "info", {}) or {}
            name = str(info.get("name") or process.name() or "")
            if name.casefold() != "vrchat.exe":
                continue
            pid = int(info.get("pid") or process.pid)
            create_time = float(info.get("create_time") or 0.0)
            matches.append(ProcessTarget(pid=pid, name=name, create_time=create_time))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    if not matches:
        return None
    return max(matches, key=lambda item: (item.create_time, item.pid))


def resolve_presentmon_path() -> Optional[Path]:
    override = os.environ.get("VRCTOOL_PRESENTMON_PATH", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    if getattr(sys, "frozen", False):
        executable_root = Path(sys.executable).resolve().parent
        bundle_root = Path(getattr(sys, "_MEIPASS", executable_root))
        candidates.extend(
            (
                executable_root / "tools" / "PresentMon.exe",
                bundle_root / "third_party" / "presentmon" / "PresentMon.exe",
                bundle_root / "PresentMon.exe",
            )
        )
    else:
        project_root = Path(__file__).resolve().parents[1]
        candidates.append(project_root / "third_party" / "presentmon" / "PresentMon.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _normalize_header(value: str) -> str:
    return "".join(character for character in value.lstrip("\ufeff") if character.isalnum()).casefold()


def _parse_float(value: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text or text.casefold() in {"na", "n/a", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class PresentMonCsvParser:
    FRAME_TIME_COLUMNS = ("msbetweenpresents", "msbetweenappstart", "frametime")

    def __init__(self) -> None:
        self._columns: Optional[list[str]] = None

    def feed_line(self, line: str | bytes) -> Optional[PresentSample]:
        if isinstance(line, bytes):
            line = line.decode("utf-8-sig", errors="replace")
        text = line.strip()
        if not text:
            return None
        try:
            values = next(csv.reader([text]))
        except (csv.Error, StopIteration):
            return None
        normalized = [_normalize_header(value) for value in values]
        if "processid" in normalized and any(item in normalized for item in self.FRAME_TIME_COLUMNS):
            self._columns = normalized
            return None
        if self._columns is None or len(values) != len(self._columns):
            return None
        row = dict(zip(self._columns, values))
        try:
            process_id = int(float(row.get("processid", "0")))
        except ValueError:
            return None
        frame_ms = None
        for column in self.FRAME_TIME_COLUMNS:
            frame_ms = _parse_float(row.get(column, ""))
            if frame_ms is not None:
                break
        if process_id <= 0 or frame_ms is None or not 0 < frame_ms <= MAX_FRAME_TIME_MS:
            return None
        present_time = _parse_float(row.get("timeinseconds", ""))
        dropped = str(row.get("dropped") or "").strip().casefold() in {
            "1",
            "true",
            "yes",
        }
        return PresentSample(
            process_id=process_id,
            swap_chain=str(row.get("swapchainaddress") or "default").strip() or "default",
            frame_ms=frame_ms,
            application=str(row.get("application") or "").strip(),
            present_time=present_time,
            dropped=dropped,
        )


class FrameWindow:
    def __init__(self, window_seconds: float = AVERAGE_WINDOW_SECONDS) -> None:
        self.window_seconds = float(window_seconds)
        self._samples: dict[str, Deque[tuple[float, float]]] = defaultdict(deque)

    def clear(self) -> None:
        self._samples.clear()

    def add(self, sample: PresentSample, observed_at: float) -> FrameMetrics:
        timeline = (
            float(sample.present_time)
            if sample.present_time is not None and sample.present_time >= 0
            else float(observed_at)
        )
        chain = self._samples[sample.swap_chain]
        chain.append((timeline, sample.frame_ms))
        return self.metrics(timeline)

    def metrics(self, now: float) -> FrameMetrics:
        cutoff = now - self.window_seconds
        empty: list[str] = []
        for address, samples in self._samples.items():
            while samples and samples[0][0] < cutoff:
                samples.popleft()
            if not samples:
                empty.append(address)
        for address in empty:
            self._samples.pop(address, None)
        if not self._samples:
            return FrameMetrics(0.0, 0.0, 0.0, "", 0)

        latest_timestamp = max(samples[-1][0] for samples in self._samples.values())
        active_chains = [
            item
            for item in self._samples.items()
            if latest_timestamp - item[1][-1][0] <= SWAP_CHAIN_RECENCY_SECONDS
        ]
        recent_cutoff = latest_timestamp - CURRENT_WINDOW_SECONDS
        address, samples = max(
            active_chains,
            key=lambda item: (
                sum(observed_at >= recent_cutoff for observed_at, _ in item[1]),
                item[1][-1][0],
                len(item[1]),
            ),
        )
        current_cutoff = latest_timestamp - CURRENT_WINDOW_SECONDS
        current_values = [frame_ms for observed_at, frame_ms in samples if observed_at >= current_cutoff]
        if not current_values:
            current_values = [samples[-1][1]]
        all_values = [frame_ms for _, frame_ms in samples]
        current_frame_ms = statistics.fmean(current_values)
        average_frame_ms = statistics.fmean(all_values)
        return FrameMetrics(
            fps=1000.0 / current_frame_ms,
            avg_fps=1000.0 / average_frame_ms,
            frame_ms=current_frame_ms,
            swap_chain=address,
            sample_count=len(samples),
        )


def format_performance_message(
    fps: float,
    avg_fps: float,
    frame_ms: float,
    *,
    show_avg_fps: bool = False,
    show_frame_ms: bool = True,
) -> str:
    parts = [f"FPS: {float(fps):.1f}"]
    if show_avg_fps:
        parts.append(f"AVG: {float(avg_fps):.1f}")
    if show_frame_ms:
        parts.append(f"Frame: {float(frame_ms):.1f}ms")
    return " | ".join(parts)[:240]


class PerformanceManager:
    def __init__(
        self,
        state: RuntimeState,
        send_message: Callable[[str], None],
        *,
        presentmon_path: Optional[Path] = None,
        process_finder: Callable[[], Optional[ProcessTarget]] = find_vrchat_process,
        subprocess_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
        clock: Callable[[], float] = time.monotonic,
        platform_name: Optional[str] = None,
    ) -> None:
        self.state = state
        self.send_message = send_message
        self.presentmon_path = Path(presentmon_path) if presentmon_path else resolve_presentmon_path()
        self._process_finder = process_finder
        self._subprocess_factory = subprocess_factory
        self._clock = clock
        self._windows_supported = (platform_name or os.name) == "nt"
        self._monitor_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        self._collector_process: Any = None
        self._reader_tasks: list[asyncio.Task] = []
        self._bound_pid = 0
        self._session_name = PERFORMANCE_SESSION_NAME
        self._session_active = False
        # Serializes collector lifecycle (start/stop/reconcile/configure/shutdown)
        # so the monitor loop and the config endpoint can't interleave and, e.g.,
        # let a stale "logman stop" tear down a freshly restarted session.
        self._lifecycle_lock = asyncio.Lock()
        self._window = FrameWindow()
        self._last_sample_at = 0.0
        self._last_sent_at: Optional[float] = None
        self._retry_at = 0.0
        self._blocked_pid = 0
        self._stderr_lines: Deque[str] = deque(maxlen=8)
        self._stopping = False
        available = self._windows_supported and self.presentmon_path is not None
        status = "等待 VRChat 启动" if available else "性能采集不可用"
        if not self._windows_supported:
            reason = "游戏帧率采集仅支持 Windows"
        elif self.presentmon_path is None:
            reason = "未找到随程序提供的 PresentMon.exe"
        else:
            reason = "未检测到 VRChat.exe"
        self.state.patch(
            "performance",
            available=available,
            collector=f"PresentMon {PRESENTMON_VERSION}" if available else "",
            status=status,
            reason=reason,
        )

    async def start(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            return
        self._stopping = False
        async with self._lifecycle_lock:
            await self._cleanup_stale_sessions()
            if self.state.snapshot()["performance"].get("broadcast_enabled"):
                self._ensure_broadcast_task()
            await self._reconcile_locked()
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(),
            name="vrctool-performance-monitor",
        )

    async def configure(
        self,
        enabled: bool,
        interval: float,
        low_fps_threshold: float,
        show_avg_fps: bool,
        show_frame_ms: bool,
    ) -> None:
        interval = max(1.0, min(float(interval), 60.0))
        threshold = max(1.0, min(float(low_fps_threshold), 240.0))
        async with self._lifecycle_lock:
            was_enabled = bool(self.state.snapshot()["performance"].get("broadcast_enabled"))
            self.state.patch(
                "performance",
                broadcast_enabled=bool(enabled),
                interval=interval,
                low_fps_threshold=threshold,
                show_avg_fps=bool(show_avg_fps),
                show_frame_ms=bool(show_frame_ms),
            )
            self._refresh_low_fps()
            if enabled:
                if not was_enabled:
                    self._last_sent_at = None
                self._ensure_broadcast_task()
                await self._reconcile_locked()
                self.maybe_broadcast()
                if not was_enabled:
                    self.state.log("ok", f"帧率 ChatBox 广播已开启，每 {interval:g} 秒发送一次")
            else:
                await self._stop_broadcast_task()
                await self._stop_collector()
                self._blocked_pid = 0
                self._retry_at = 0.0
                self._last_sent_at = None
                self._reset_samples()
                vrchat_running = bool(self.state.snapshot()["performance"].get("vrchat_running"))
                self.state.patch(
                    "performance",
                    needs_permission=False,
                    relogin_required=False,
                    status="广播已关闭",
                    reason=(
                        "已检测到 VRChat.exe，开启广播后开始采样"
                        if vrchat_running
                        else "未检测到 VRChat.exe"
                    ),
                )
                if was_enabled:
                    self.state.log("ok", "帧率 ChatBox 广播已关闭")

    async def shutdown(self) -> None:
        self._stopping = True
        monitor = self._monitor_task
        self._monitor_task = None
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await self._stop_broadcast_task()
        async with self._lifecycle_lock:
            await self._stop_collector()
            self._bound_pid = 0
            self._reset_samples()
            self.state.patch(
                "performance",
                vrchat_running=False,
                process_id=0,
                sampling=False,
                status="已停止",
                reason="vrctool 正在关闭",
            )

    async def reconcile_once(self) -> None:
        async with self._lifecycle_lock:
            await self._reconcile_locked()

    async def _reconcile_locked(self) -> None:
        now = self._clock()
        if not self._windows_supported or self.presentmon_path is None:
            await self._stop_collector()
            return
        broadcast_enabled = bool(
            self.state.snapshot()["performance"].get("broadcast_enabled")
        )
        target = self._process_finder()
        if target is None:
            if self._collector_process is not None or self._bound_pid:
                await self._stop_collector()
            self._bound_pid = 0
            self._blocked_pid = 0
            self._retry_at = 0.0
            self._last_sent_at = None
            self._reset_samples()
            self.state.patch(
                "performance",
                available=True,
                vrchat_running=False,
                process_id=0,
                sampling=False,
                needs_permission=False,
                relogin_required=False,
                status="等待 VRChat 启动" if broadcast_enabled else "广播已关闭",
                reason="未检测到 VRChat.exe",
            )
            return

        self.state.patch("performance", vrchat_running=True, process_id=target.pid)
        if not broadcast_enabled:
            if self._collector_process is not None:
                await self._stop_collector()
            if target.pid != self._bound_pid:
                self._bound_pid = target.pid
                self._blocked_pid = 0
                self._retry_at = 0.0
                self._last_sent_at = None
                self._reset_samples()
            self.state.patch(
                "performance",
                sampling=False,
                needs_permission=False,
                relogin_required=False,
                status="广播已关闭",
                reason="已检测到 VRChat.exe，开启广播后开始采样",
            )
            return

        if target.pid != self._bound_pid:
            await self._stop_collector()
            self._bound_pid = target.pid
            self._blocked_pid = 0
            self._retry_at = 0.0
            self._last_sent_at = None
            self._reset_samples()
            await self._start_collector(target)
            return

        process = self._collector_process
        if process is not None and process.returncode is not None:
            return_code = process.returncode
            detail = "\n".join(self._stderr_lines)
            await self._stop_collector()
            reason, permission_error = self._presentmon_failure(return_code, detail)
            self._blocked_pid = target.pid if permission_error else 0
            self._retry_at = float("inf") if permission_error else now + RETRY_SECONDS
            self.state.patch(
                "performance",
                sampling=False,
                fps=0.0,
                avg_fps=0.0,
                frame_ms=0.0,
                low_fps=False,
                needs_permission=permission_error,
                status="采样失败",
                reason=reason,
            )
            self.state.log("err", reason)
            return

        if process is None and self._blocked_pid != target.pid and now >= self._retry_at:
            await self._start_collector(target)
            return

        if process is not None and self._last_sample_at and now - self._last_sample_at > SAMPLE_STALE_SECONDS:
            self.state.patch(
                "performance",
                fps=0.0,
                avg_fps=0.0,
                frame_ms=0.0,
                low_fps=False,
                status="等待帧数据",
                reason="VRChat 已运行，但暂未捕获到呈现帧",
            )

    def maybe_broadcast(self, now: Optional[float] = None) -> bool:
        now = self._clock() if now is None else float(now)
        performance = self.state.snapshot()["performance"]
        if not performance.get("broadcast_enabled"):
            return False
        if not performance.get("vrchat_running") or not performance.get("sampling"):
            return False
        if self._last_sample_at <= 0 or now - self._last_sample_at > SAMPLE_STALE_SECONDS:
            return False
        interval = max(1.0, float(performance.get("interval") or DEFAULT_INTERVAL))
        if self._last_sent_at is not None and now - self._last_sent_at < interval:
            return False
        message = format_performance_message(
            float(performance.get("fps") or 0.0),
            float(performance.get("avg_fps") or 0.0),
            float(performance.get("frame_ms") or 0.0),
            show_avg_fps=bool(performance.get("show_avg_fps")),
            show_frame_ms=bool(performance.get("show_frame_ms", True)),
        )
        if not message.strip():
            return False
        try:
            self.send_message(message)
        except Exception as exc:
            self.state.patch("performance", reason=f"ChatBox 发送失败：{exc}")
            self.state.log("err", f"帧率 ChatBox 发送失败：{exc}")
            return False
        self._last_sent_at = now
        self.state.patch(
            "performance",
            last_sent=datetime.now().strftime("%H:%M:%S"),
            last_message=message,
        )
        return True

    async def _monitor_loop(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(PROCESS_POLL_SECONDS)
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.patch("performance", status="监控失败", reason=str(exc))
                self.state.log("err", f"VRChat 帧率监控失败：{exc}")

    def _ensure_broadcast_task(self) -> None:
        if self._broadcast_task and not self._broadcast_task.done():
            return
        self._broadcast_task = asyncio.create_task(
            self._broadcast_loop(),
            name="vrctool-performance-chatbox",
        )

    async def _stop_broadcast_task(self) -> None:
        task = self._broadcast_task
        self._broadcast_task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _broadcast_loop(self) -> None:
        while self.state.snapshot()["performance"].get("broadcast_enabled"):
            self.maybe_broadcast()
            await asyncio.sleep(0.2)

    async def _start_collector(self, target: ProcessTarget) -> None:
        if self.presentmon_path is None:
            return
        self._stderr_lines.clear()
        self._session_name = PERFORMANCE_SESSION_NAME
        command = [
            str(self.presentmon_path),
            "--process_id",
            str(target.pid),
            "--output_stdout",
            "--no_console_stats",
            "--v1_metrics",
            "--no_track_gpu",
            "--no_track_input",
            "--terminate_on_proc_exit",
            "--session_name",
            self._session_name,
            "--stop_existing_session",
        ]
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        # Mark the session active before the spawn: PresentMon can create its
        # ETW session during spawn, so even a cancellation mid-spawn must leave
        # teardown able to stop it.
        self._session_active = True
        try:
            process = await self._subprocess_factory(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.presentmon_path.parent),
                creationflags=creation_flags,
            )
        except (OSError, RuntimeError) as exc:
            self._session_active = False
            self._collector_process = None
            self._retry_at = self._clock() + RETRY_SECONDS
            self.state.patch(
                "performance",
                sampling=False,
                status="采样失败",
                reason=f"无法启动 PresentMon：{exc}",
            )
            return
        self._collector_process = process
        self._reader_tasks = [
            asyncio.create_task(self._read_samples(process, target.pid)),
            asyncio.create_task(self._read_stderr(process)),
        ]
        self.state.patch(
            "performance",
            available=True,
            vrchat_running=True,
            process_id=target.pid,
            sampling=True,
            needs_permission=False,
            relogin_required=False,
            status="等待帧数据",
            reason="PresentMon 已绑定，等待 VRChat 呈现帧",
        )
        self.state.log("ok", f"PresentMon 已绑定 VRChat.exe（PID {target.pid}）")

    async def _read_samples(self, process: Any, process_id: int) -> None:
        parser = PresentMonCsvParser()
        stream = process.stdout
        if stream is None:
            return
        while self._collector_process is process and self._bound_pid == process_id:
            line = await stream.readline()
            if not line:
                break
            sample = parser.feed_line(line)
            if sample is None or sample.process_id != process_id:
                continue
            self._ingest_sample(sample)

    async def _read_stderr(self, process: Any) -> None:
        stream = process.stderr
        if stream is None:
            return
        while self._collector_process is process:
            line = await stream.readline()
            if not line:
                break
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                self._stderr_lines.append(message)

    def _ingest_sample(self, sample: PresentSample) -> None:
        now = self._clock()
        self._last_sample_at = now
        metrics = self._window.add(sample, now)
        threshold = float(
            self.state.snapshot()["performance"].get("low_fps_threshold")
            or DEFAULT_LOW_FPS_THRESHOLD
        )
        self.state.patch(
            "performance",
            sampling=True,
            fps=round(metrics.fps, 1),
            avg_fps=round(metrics.avg_fps, 1),
            frame_ms=round(metrics.frame_ms, 1),
            low_fps=0 < metrics.fps < threshold,
            active_swap_chain=metrics.swap_chain,
            sample_count=metrics.sample_count,
            needs_permission=False,
            relogin_required=False,
            status="采样中",
            reason="",
            last_sample=datetime.now().strftime("%H:%M:%S"),
        )

    async def _stop_collector(self) -> None:
        process = self._collector_process
        self._collector_process = None
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
                await asyncio.gather(process.wait(), return_exceptions=True)
        tasks = self._reader_tasks
        self._reader_tasks = []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._session_active:
            self._session_active = False
            await self._stop_trace_session()
        self.state.patch("performance", sampling=False)

    async def _logman_stop(self, name: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "logman",
                "stop",
                name,
                "-ets",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except (OSError, RuntimeError, ValueError, asyncio.TimeoutError):
            pass

    async def _stop_trace_session(self) -> None:
        # PresentMon is hard-terminated, so its real-time ETW session is left
        # running. Stop it explicitly so sessions never accumulate; the next
        # start also reclaims it via --stop_existing_session, so failure here is
        # harmless.
        if not self._windows_supported or not self._session_name:
            return
        await self._logman_stop(self._session_name)

    async def _cleanup_stale_sessions(self) -> None:
        # Clear ETW sessions orphaned by earlier runs — including legacy per-PID
        # "vrctool-performance-<pid>" names from older builds — so a leaked
        # session can't starve ETW and leave capture bound-but-0-fps.
        if not self._windows_supported:
            return
        try:
            process = await asyncio.create_subprocess_exec(
                "logman",
                "query",
                "-ets",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)
        except (OSError, RuntimeError, ValueError, asyncio.TimeoutError):
            return
        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        prefix = PERFORMANCE_SESSION_NAME.casefold()
        names: list[str] = []
        for line in text.splitlines():
            token = line.strip().split()
            if token and token[0].casefold().startswith(prefix) and token[0] not in names:
                names.append(token[0])
        for name in names:
            await self._logman_stop(name)

    def _reset_samples(self) -> None:
        self._window.clear()
        self._last_sample_at = 0.0
        self.state.patch(
            "performance",
            fps=0.0,
            avg_fps=0.0,
            frame_ms=0.0,
            low_fps=False,
            active_swap_chain="",
            sample_count=0,
            last_sample="",
        )

    def _refresh_low_fps(self) -> None:
        performance = self.state.snapshot()["performance"]
        fps = float(performance.get("fps") or 0.0)
        threshold = float(performance.get("low_fps_threshold") or DEFAULT_LOW_FPS_THRESHOLD)
        self.state.patch("performance", low_fps=0 < fps < threshold)

    async def request_capture_permission(self) -> dict[str, Any]:
        if not self._windows_supported:
            return {
                "ok": False,
                "status": "unsupported",
                "message": "游戏帧率采集仅支持 Windows",
            }
        outcome, detail = await asyncio.to_thread(self._elevate_join_group)
        if outcome == "ok":
            self.state.patch(
                "performance",
                needs_permission=False,
                relogin_required=True,
                status="待重新登录",
                reason="已加入 Performance Log Users 组，请注销并重新登录（或重启）后生效",
            )
            self.state.log(
                "ok", "已将当前用户加入 Performance Log Users 组，注销重登后生效"
            )
            return {
                "ok": True,
                "status": "relogin",
                "message": "已加入 Performance Log Users 组，请注销并重新登录后生效",
            }
        if outcome == "cancelled":
            self.state.log("warn", "已取消加入 Performance Log Users 组")
            return {"ok": False, "status": "cancelled", "message": detail or "已取消授权"}
        self.state.log("err", f"加入 Performance Log Users 组失败：{detail}")
        return {"ok": False, "status": "error", "message": detail}

    @staticmethod
    def _current_account_name() -> str:
        domain = os.environ.get("USERDOMAIN", "").strip()
        user = os.environ.get("USERNAME", "").strip()
        if domain and user:
            return f"{domain}\\{user}"
        return user

    def _elevate_join_group(self) -> tuple[str, str]:
        member = self._current_account_name()
        if not member:
            return "error", "无法确定当前 Windows 账户名"
        script = _GRANT_SCRIPT_TEMPLATE.replace("__MEMBER__", member)
        script_path = Path(tempfile.gettempdir()) / f"vrctool-grant-{os.getpid()}.ps1"
        try:
            script_path.write_text(script, encoding="utf-8")
        except OSError as exc:
            return "error", f"无法写入临时脚本：{exc}"
        outer = _GRANT_OUTER_TEMPLATE.replace("__SCRIPT__", str(script_path))
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", outer],
                capture_output=True,
                text=True,
                timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return "error", f"无法启动提权流程：{exc}"
        finally:
            try:
                script_path.unlink()
            except OSError:
                pass
        if completed.returncode == 0:
            return "ok", ""
        if completed.returncode == 1223:
            return "cancelled", "已取消授权（未加入组）"
        detail = " ".join((completed.stderr or completed.stdout or "").split())
        return "error", detail[:180] or f"加入组失败（代码 {completed.returncode}）"

    @staticmethod
    def _presentmon_failure(return_code: int, detail: str) -> tuple[str, bool]:
        text = detail.casefold()
        if "access denied" in text or "performance log users" in text:
            return (
                "PresentMon 权限不足：请以管理员身份运行 vrctool，或将当前用户加入 "
                "Performance Log Users 组后重新登录",
                True,
            )
        concise = " ".join(line.strip() for line in detail.splitlines() if line.strip())
        if concise:
            return f"PresentMon 已退出（代码 {return_code}）：{concise[:180]}", False
        return f"PresentMon 已退出（代码 {return_code}）", False
