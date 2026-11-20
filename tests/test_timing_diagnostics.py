"""Numerical evidence from real queues/SQLite; no device or application settings."""

import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from stackchan_autonomy.async_storage import AsyncStorage


async def wait_thread(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def test_serial_admission_and_cancelled_waiter_are_distinguished():
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe = TimingProbe()
    storage = AsyncStorage()
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        release.wait(3)

    with probe.collect():
        first = asyncio.create_task(storage.call(blocked))
        try:
            await wait_thread(entered)
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.04):
                    await storage.call(lambda: None)
            interruption = probe.snapshot()["interruptions"][-1]
            assert interruption["stage"] == "serial_wait"
            assert interruption["elapsed_s"] >= 0.03
        finally:
            release.set()
            await first
            await storage.aclose()
    stats = probe.snapshot()["stages"]
    assert stats["storage_operation"]["count"] == 1
    assert stats["storage_serial_wait"]["count"] == 2


async def test_shared_executor_queue_is_distinct_from_operation():
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe = TimingProbe()
    storage = AsyncStorage()
    entered, release = threading.Event(), threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()
    original_submit = loop.run_in_executor

    def block_pool():
        entered.set()
        release.wait(3)

    blocker = executor.submit(block_pool)
    await wait_thread(entered)
    try:
        # Patch only this storage submission, without replacing the loop's pool.
        from unittest.mock import patch

        with (
            probe.collect(),
            patch.object(
                loop,
                "run_in_executor",
                side_effect=lambda _, fn, *args: original_submit(executor, fn, *args),
            ),
        ):
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.04):
                    await storage.call(lambda: 7)
            assert probe.snapshot()["interruptions"][-1]["stage"] == "executor_wait"
            release.set()
            await storage.aclose()
        stats = probe.snapshot()["stages"]
        assert stats["storage_executor_wait"]["max_s"] >= 0.03
        assert stats["storage_operation"]["count"] == 1
    finally:
        release.set()
        blocker.result(timeout=3)
        executor.shutdown()


async def test_cancellation_after_worker_completion_keeps_delivery_stage():
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe, storage = TimingProbe(), AsyncStorage()
    original_finished = storage._finished
    task = None

    def cancel_before_delivery(future):
        original_finished(future)
        task.cancel()

    storage._finished = cancel_before_delivery
    with probe.collect():
        task = asyncio.create_task(storage.call(lambda: 7))
        with pytest.raises(asyncio.CancelledError):
            await task
        await storage.aclose()
    assert probe.snapshot()["interruptions"][-1]["stage"] == "delivery"
    assert not storage.pending and not storage._slot.locked()


async def test_sqlite_writer_contention_is_measured_without_exporting_details(tmp_path):
    from stackchan_autonomy.state_store import SQLiteState, StateUnavailable
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    path = tmp_path / "private-path-secret.sqlite3"
    store = SQLiteState(path)
    with store.transaction():
        pass
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    probe, storage = TimingProbe(), AsyncStorage()

    def work():
        with store.transaction():
            raise AssertionError("lock should reject before body")

    try:
        with probe.collect():
            with pytest.raises(StateUnavailable):
                await storage.call(work)
            await storage.aclose()
    finally:
        db.rollback()
        db.close()
    stats = probe.snapshot()["stages"]
    assert stats["sqlite_begin"]["max_s"] >= 0.15
    assert stats["storage_operation"]["max_s"] >= stats["sqlite_begin"]["max_s"]
    assert "sqlite_commit" not in stats
    assert "private-path-secret" not in json.dumps(probe.snapshot())


async def test_result_delivery_and_loop_stall_are_measured_separately():
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe, storage = TimingProbe(), AsyncStorage()
    entered, done = threading.Event(), threading.Event()

    def work():
        entered.set()
        done.set()
        return 7

    with probe.collect():
        probe.start_loop_monitor(asyncio.get_running_loop(), interval_s=0.01)
        try:
            task = asyncio.create_task(storage.call(work))
            # Block the loop only AFTER submission; the worker still completes.
            while not entered.is_set():
                await asyncio.sleep(0)
            time.sleep(0.06)
            assert done.is_set()
            assert await task == 7
            await asyncio.sleep(0.02)
            await storage.aclose()
        finally:
            probe.stop_loop_monitor()
    report = probe.snapshot()
    assert report["stages"]["storage_delivery"]["max_s"] >= 0.04
    assert report["loop_lag_max_s"] >= 0.04


async def test_diagnostics_are_bounded_and_operation_labels_are_allowlisted():
    from stackchan_autonomy.timing_diagnostics import TimingProbe, operation_label

    probe, storage = TimingProbe(), AsyncStorage()
    with probe.collect(), operation_label("private-token-never-export"):
        for _ in range(40):
            # This semaphore remains owned by a real submitted worker.
            storage._slot = asyncio.Lock()
            await storage._slot.acquire()
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.001):
                    await storage.call(lambda: None)
            storage._slot.release()
        await storage.aclose()
    report = probe.snapshot()
    assert report["interruption_count"] == 40
    assert len(report["interruptions"]) == 16
    assert "private-token-never-export" not in json.dumps(report)


async def test_soak_opt_in_report_keeps_failures_and_no_monitor_task_leak():
    from stackchan_autonomy.soak import SoakConfig, run_soak

    report = await run_soak(
        SoakConfig(cycles=8, warmup_cycles=2, diagnostics=True, virtual_step_s=30)
    )
    assert report.passed and report.remaining_tasks == 0
    timing = report.timing_diagnostics
    assert timing["stages"]["sqlite_commit"]["count"] > 0
    assert timing["operations"]["lease_check"] > 0
    assert report.cloud_requests == 0


async def test_measured_slow_lease_worker_still_fails_closed_without_retry(monkeypatch):
    from stackchan_autonomy import soak
    from stackchan_autonomy.control import ControlLease

    original_engine = soak.AutonomyEngine
    original_check = ControlLease.check
    calls = 0

    def short_test_lease(robot, provider, settings, **kwargs):
        return original_engine(
            robot, provider, settings.model_copy(update={"lease_ttl_s": 0.1}), **kwargs
        )

    def slow_check(self, handle):
        nonlocal calls
        calls += 1
        time.sleep(0.15)
        return original_check(self, handle)

    monkeypatch.setattr(soak, "AutonomyEngine", short_test_lease)
    monkeypatch.setattr(ControlLease, "check", slow_check)
    report = await soak.run_soak(soak.SoakConfig(cycles=8, warmup_cycles=1, diagnostics=True))
    assert not report.passed and "engine_failure" in report.violations
    assert report.failure.control_loss_reason in {"check_timeout", "renew_timeout"}
    assert report.failure.lease_lost and report.failure.action_stopped
    assert calls == 1 and report.cloud_requests == report.remaining_tasks == 0
    timing = report.timing_diagnostics
    assert timing["stages"]["storage_operation"]["max_s"] >= 0.14
    assert any(r["stage"] in {"operation", "serial_wait"} for r in timing["interruptions"])
