from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vrctool_app.performance import (
    PERFORMANCE_SESSION_NAME,
    FrameWindow,
    PerformanceManager,
    PresentMonCsvParser,
    PresentSample,
    ProcessTarget,
    find_vrchat_process,
    format_performance_message,
)
from vrctool_app.state import RuntimeState


class FakeProcessDescription:
    def __init__(self, pid: int, name: str, create_time: float) -> None:
        self.pid = pid
        self.info = {"pid": pid, "name": name, "create_time": create_time}


class FakeCollectorProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminate_called = False
        self.kill_called = False
        self.stdout = None
        self.stderr = None

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = 0

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -1

    async def wait(self) -> int:
        return int(self.returncode or 0)


class PerformanceParsingTests(unittest.TestCase):
    def test_vrchat_process_detection_prefers_latest_process(self) -> None:
        processes = [
            FakeProcessDescription(100, "Other.exe", 9.0),
            FakeProcessDescription(200, "vrchat.exe", 10.0),
            FakeProcessDescription(300, "VRChat.exe", 11.0),
        ]

        target = find_vrchat_process(processes)

        self.assertEqual(target, ProcessTarget(pid=300, name="VRChat.exe", create_time=11.0))

    def test_presentmon_csv_parser_reads_process_swap_chain_and_frame_time(self) -> None:
        parser = PresentMonCsvParser()
        self.assertIsNone(parser.feed_line("warning: waiting for target"))
        self.assertIsNone(
            parser.feed_line(
                "Application,ProcessID,SwapChainAddress,Dropped,TimeInSeconds,MsBetweenPresents"
            )
        )

        sample = parser.feed_line("VRChat.exe,456,0x00001234,1,12.345,11.111")

        self.assertEqual(sample.process_id, 456)
        self.assertEqual(sample.swap_chain, "0x00001234")
        self.assertAlmostEqual(sample.frame_ms, 11.111)
        self.assertAlmostEqual(sample.present_time, 12.345)
        self.assertTrue(sample.dropped)

    def test_frame_window_uses_one_dominant_swap_chain(self) -> None:
        window = FrameWindow(window_seconds=5.0)
        metrics = None
        for index in range(10):
            metrics = window.add(PresentSample(1, "primary", 10.0), 10.0 + index * 0.01)
        for index in range(3):
            metrics = window.add(PresentSample(1, "mirror", 5.0), 10.2 + index * 0.01)

        self.assertEqual(metrics.swap_chain, "primary")
        self.assertAlmostEqual(metrics.fps, 100.0)
        self.assertEqual(metrics.sample_count, 10)

    def test_frame_window_switches_away_from_stale_swap_chain(self) -> None:
        window = FrameWindow(window_seconds=5.0)
        metrics = None
        for index in range(100):
            metrics = window.add(
                PresentSample(1, "old", 5.0, present_time=index * 0.01),
                100.0,
            )
        for index in range(10):
            metrics = window.add(
                PresentSample(1, "current", 12.5, present_time=4.0 + index * 0.01),
                100.0,
            )

        self.assertEqual(metrics.swap_chain, "current")
        self.assertAlmostEqual(metrics.fps, 80.0)

    def test_frame_window_uses_presentmon_event_time_instead_of_read_time(self) -> None:
        window = FrameWindow(window_seconds=5.0)
        window.add(PresentSample(1, "main", 10.0, present_time=0.0), 100.0)
        metrics = window.add(PresentSample(1, "main", 20.0, present_time=10.0), 100.0)

        self.assertEqual(metrics.sample_count, 1)
        self.assertAlmostEqual(metrics.fps, 50.0)

    def test_ingest_uses_latest_sample_even_when_rows_arrive_together(self) -> None:
        state = RuntimeState()
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            clock=lambda: 100.0,
            platform_name="nt",
        )

        manager._ingest_sample(PresentSample(1, "main", 10.0, present_time=1.0))
        manager._ingest_sample(PresentSample(1, "main", 20.0, present_time=1.01))
        performance = state.snapshot()["performance"]

        self.assertEqual(performance["sample_count"], 2)
        self.assertEqual(performance["frame_ms"], 15.0)
        self.assertEqual(performance["fps"], 66.7)

    def test_message_lists_only_enabled_metrics(self) -> None:
        fps, avg_fps, frame_ms = 72.3, 69.0, 13.9

        self.assertEqual(
            format_performance_message(fps, avg_fps, frame_ms),
            "FPS: 72.3 | Frame: 13.9ms",
        )
        self.assertEqual(
            format_performance_message(fps, avg_fps, frame_ms, show_avg_fps=True, show_frame_ms=True),
            "FPS: 72.3 | AVG: 69.0 | Frame: 13.9ms",
        )
        self.assertEqual(
            format_performance_message(fps, avg_fps, frame_ms, show_avg_fps=True, show_frame_ms=False),
            "FPS: 72.3 | AVG: 69.0",
        )
        # FPS is always broadcast, even with every optional metric disabled.
        self.assertEqual(
            format_performance_message(fps, avg_fps, frame_ms, show_avg_fps=False, show_frame_ms=False),
            "FPS: 72.3",
        )

    def test_broadcast_sends_immediately_then_throttles_for_three_seconds(self) -> None:
        state = RuntimeState()
        messages: list[str] = []
        manager = PerformanceManager(
            state,
            messages.append,
            presentmon_path=Path(__file__),
            platform_name="nt",
        )
        state.patch(
            "performance",
            broadcast_enabled=True,
            interval=3.0,
            vrchat_running=True,
            sampling=True,
            fps=72.3,
            avg_fps=69.0,
            frame_ms=13.9,
        )
        manager._last_sample_at = 10.0

        self.assertTrue(manager.maybe_broadcast(now=10.0))
        self.assertFalse(manager.maybe_broadcast(now=12.99))
        self.assertTrue(manager.maybe_broadcast(now=13.0))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], "FPS: 72.3 | Frame: 13.9ms")

    def test_broadcast_message_follows_enabled_metric_toggles(self) -> None:
        state = RuntimeState()
        messages: list[str] = []
        manager = PerformanceManager(
            state,
            messages.append,
            presentmon_path=Path(__file__),
            platform_name="nt",
        )
        state.patch(
            "performance",
            broadcast_enabled=True,
            interval=3.0,
            vrchat_running=True,
            sampling=True,
            fps=72.3,
            avg_fps=69.0,
            frame_ms=13.9,
            show_avg_fps=True,
            show_frame_ms=True,
        )
        manager._last_sample_at = 10.0

        self.assertTrue(manager.maybe_broadcast(now=10.0))
        self.assertEqual(messages[0], "FPS: 72.3 | AVG: 69.0 | Frame: 13.9ms")

    def test_access_denied_is_reported_as_a_permission_error(self) -> None:
        reason, blocked = PerformanceManager._presentmon_failure(
            6,
            'error: failed to start trace session: access denied. Join "Performance Log Users".',
        )

        self.assertTrue(blocked)
        self.assertIn("权限不足", reason)


class PerformanceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_exit_stops_sending_and_cleans_collector_resources(self) -> None:
        state = RuntimeState()
        messages: list[str] = []
        manager = PerformanceManager(
            state,
            messages.append,
            presentmon_path=Path(__file__),
            process_finder=lambda: None,
            platform_name="nt",
        )
        collector = FakeCollectorProcess()
        reader = asyncio.create_task(asyncio.sleep(60))
        manager._collector_process = collector
        manager._reader_tasks = [reader]
        manager._bound_pid = 456
        manager._last_sample_at = 20.0
        state.patch(
            "performance",
            broadcast_enabled=True,
            vrchat_running=True,
            process_id=456,
            sampling=True,
            fps=72.0,
            avg_fps=70.0,
            frame_ms=13.9,
        )

        await manager.reconcile_once()

        performance = state.snapshot()["performance"]
        self.assertTrue(collector.terminate_called)
        self.assertTrue(reader.cancelled())
        self.assertFalse(performance["vrchat_running"])
        self.assertFalse(performance["sampling"])
        self.assertEqual(performance["fps"], 0.0)
        self.assertFalse(manager.maybe_broadcast(now=20.0))
        self.assertEqual(messages, [])

    async def test_new_vrchat_pid_replaces_old_collector(self) -> None:
        state = RuntimeState()
        state.patch("performance", broadcast_enabled=True)
        target = ProcessTarget(pid=789, create_time=30.0)
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            process_finder=lambda: target,
            platform_name="nt",
        )
        old_collector = FakeCollectorProcess()
        manager._collector_process = old_collector
        manager._bound_pid = 456

        with patch.object(manager, "_start_collector", new=AsyncMock()) as start_collector:
            await manager.reconcile_once()

        self.assertTrue(old_collector.terminate_called)
        self.assertEqual(manager._bound_pid, 789)
        start_collector.assert_awaited_once_with(target)

    async def test_collector_stays_stopped_until_broadcast_is_enabled(self) -> None:
        state = RuntimeState()
        target = ProcessTarget(pid=789, create_time=30.0)
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            process_finder=lambda: target,
            platform_name="nt",
        )

        with patch.object(manager, "_start_collector", new=AsyncMock()) as start_collector:
            await manager.reconcile_once()

        performance = state.snapshot()["performance"]
        start_collector.assert_not_awaited()
        self.assertTrue(performance["vrchat_running"])
        self.assertFalse(performance["sampling"])
        self.assertEqual(performance["status"], "广播已关闭")

    async def test_monitor_stops_stray_collector_while_broadcast_disabled(self) -> None:
        state = RuntimeState()
        target = ProcessTarget(pid=456, create_time=30.0)
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            process_finder=lambda: target,
            platform_name="nt",
        )
        collector = FakeCollectorProcess()
        reader = asyncio.create_task(asyncio.sleep(60))
        manager._collector_process = collector
        manager._reader_tasks = [reader]
        manager._bound_pid = 456
        state.patch("performance", broadcast_enabled=False, sampling=True)

        await manager.reconcile_once()

        performance = state.snapshot()["performance"]
        self.assertTrue(collector.terminate_called)
        self.assertTrue(reader.cancelled())
        self.assertIsNone(manager._collector_process)
        self.assertTrue(performance["vrchat_running"])
        self.assertFalse(performance["sampling"])
        self.assertEqual(performance["status"], "广播已关闭")

    async def test_disabling_broadcast_cleans_collector_resources(self) -> None:
        state = RuntimeState()
        state.patch(
            "performance",
            broadcast_enabled=True,
            vrchat_running=True,
            process_id=456,
            sampling=True,
            fps=72.0,
            avg_fps=70.0,
            frame_ms=13.9,
        )
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            platform_name="nt",
        )
        collector = FakeCollectorProcess()
        reader = asyncio.create_task(asyncio.sleep(60))
        manager._collector_process = collector
        manager._reader_tasks = [reader]
        manager._bound_pid = 456

        await manager.configure(False, 3.0, 45.0, False, True)

        performance = state.snapshot()["performance"]
        self.assertTrue(collector.terminate_called)
        self.assertTrue(reader.cancelled())
        self.assertFalse(performance["broadcast_enabled"])
        self.assertFalse(performance["sampling"])
        self.assertEqual(performance["fps"], 0.0)
        self.assertEqual(performance["status"], "广播已关闭")

    async def test_grant_permission_success_requires_relogin(self) -> None:
        state = RuntimeState()
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            platform_name="nt",
        )
        state.patch("performance", needs_permission=True)

        with patch.object(manager, "_elevate_join_group", return_value=("ok", "")):
            result = await manager.request_capture_permission()

        performance = state.snapshot()["performance"]
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "relogin")
        self.assertFalse(performance["needs_permission"])
        self.assertTrue(performance["relogin_required"])

    async def test_grant_permission_cancelled_keeps_prompt(self) -> None:
        state = RuntimeState()
        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            platform_name="nt",
        )
        state.patch("performance", needs_permission=True)

        with patch.object(
            manager, "_elevate_join_group", return_value=("cancelled", "已取消授权")
        ):
            result = await manager.request_capture_permission()

        performance = state.snapshot()["performance"]
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(performance["needs_permission"])
        self.assertFalse(performance["relogin_required"])

    async def test_start_collector_marks_session_and_stop_releases_it(self) -> None:
        state = RuntimeState()
        collector = FakeCollectorProcess()

        async def factory(*_args, **_kwargs):
            return collector

        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            subprocess_factory=factory,
            platform_name="nt",
        )
        stopped: list[str] = []

        async def fake_logman(name: str) -> None:
            stopped.append(name)

        manager._logman_stop = fake_logman  # type: ignore[assignment]

        await manager._start_collector(ProcessTarget(pid=321, create_time=1.0))
        self.assertTrue(manager._session_active)
        self.assertIs(manager._collector_process, collector)

        await manager._stop_collector()
        self.assertFalse(manager._session_active)
        self.assertTrue(collector.terminate_called)
        self.assertEqual(stopped, [PERFORMANCE_SESSION_NAME])

    async def test_failed_spawn_clears_session_active(self) -> None:
        state = RuntimeState()

        async def failing_factory(*_args, **_kwargs):
            raise OSError("spawn failed")

        manager = PerformanceManager(
            state,
            lambda _message: None,
            presentmon_path=Path(__file__),
            subprocess_factory=failing_factory,
            platform_name="nt",
        )

        await manager._start_collector(ProcessTarget(pid=321, create_time=1.0))

        self.assertFalse(manager._session_active)
        self.assertIsNone(manager._collector_process)


if __name__ == "__main__":
    unittest.main()
