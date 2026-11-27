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


async def test_serial_admission_and_cancelled_waiter_are_distinguished(monkeypatch):
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe = TimingProbe()
    storage = AsyncStorage()
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        release.wait(3)

    original_acquire = storage._slot.acquire
    observed_wait = {}

    async def observed_acquire():
        # Tracing has started before this call; cancellation is recorded after
        # this handler. Its real elapsed interval must fit inside the metric.
        observed_wait["start"] = time.perf_counter()
        try:
            return await original_acquire()
        except asyncio.CancelledError:
            observed_wait["cancel"] = time.perf_counter()
            raise

    with probe.collect():
        first = asyncio.create_task(storage.call(blocked))
        try:
            await wait_thread(entered)
            monkeypatch.setattr(storage._slot, "acquire", observed_acquire)
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.04):
                    await storage.call(lambda: None)
            interruption = probe.snapshot()["interruptions"][-1]
            assert interruption["stage"] == "serial_wait"
            measured_wait = observed_wait["cancel"] - observed_wait["start"]
            assert measured_wait > 0
            assert interruption["elapsed_s"] >= measured_wait
        finally:
            release.set()
            await first
            await storage.aclose()
    stats = probe.snapshot()["stages"]
    assert stats["storage_operation"]["count"] == 1
    assert stats["storage_serial_wait"]["count"] == 2
    assert stats["storage_serial_wait"]["max_s"] >= measured_wait


async def test_shared_executor_queue_is_distinct_from_operation():
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe = TimingProbe()
    storage = AsyncStorage()
    entered, release = threading.Event(), threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()
    original_submit = loop.run_in_executor
    observed_queue = {}

    def shared_submit(_, fn, *args):
        # The executor_wait trace began before this submission, and the pool
        # cannot run it until release.set() below. Keep the real clock/queue.
        observed_queue["start"] = time.perf_counter()
        return original_submit(executor, fn, *args)

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
                side_effect=shared_submit,
            ),
        ):
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.04):
                    await storage.call(lambda: 7)
            assert probe.snapshot()["interruptions"][-1]["stage"] == "executor_wait"
            assert not blocker.done()
            observed_queue["release"] = time.perf_counter()
            release.set()
            await storage.aclose()
        stats = probe.snapshot()["stages"]
        measured_queue = observed_queue["release"] - observed_queue["start"]
        assert measured_queue > 0
        assert stats["storage_executor_wait"]["max_s"] >= measured_queue
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


@pytest.mark.parametrize("blocked_stage", ["sqlite_begin", "sqlite_commit"])
async def test_sqlite_lock_contention_is_measured_without_exporting_details(
    tmp_path, blocked_stage
):
    from stackchan_autonomy.state_store import SQLiteState, StateUnavailable
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    path = tmp_path / "private-path-secret.sqlite3"
    store = SQLiteState(path)
    with store.transaction():
        pass
    db = sqlite3.connect(path, isolation_level=None)
    if blocked_stage == "sqlite_begin":
        db.execute("BEGIN IMMEDIATE")
    else:
        # In the default rollback journal a reader allows BEGIN IMMEDIATE and
        # writes, but holds the lock that COMMIT needs to publish them.
        db.execute("BEGIN")
        assert db.execute("SELECT count(*) FROM autonomy_clock").fetchone() == (0,)
    probe, storage = TimingProbe(), AsyncStorage()

    def work():
        with store.transaction() as tx:
            assert blocked_stage == "sqlite_commit"
            store.observed_time(tx, "rollback-probe", 1)

    try:
        with probe.collect():
            with pytest.raises(StateUnavailable):
                await storage.call(work)
            await storage.aclose()
    finally:
        db.rollback()
        db.close()
    stats = probe.snapshot()["stages"]
    assert stats[blocked_stage]["max_s"] >= 0.15
    assert stats["storage_operation"]["max_s"] >= stats[blocked_stage]["max_s"]
    if blocked_stage == "sqlite_begin":
        assert "sqlite_commit" not in stats
    with store.transaction() as tx:
        assert tx.execute("SELECT count(*) FROM autonomy_clock").fetchone() == (0,)
    assert "private-path-secret" not in json.dumps(probe.snapshot())


def test_interruption_reports_time_in_the_current_sqlite_stage(monkeypatch):
    from types import SimpleNamespace

    from stackchan_autonomy import timing_diagnostics as timings

    now = 10
    monkeypatch.setattr(timings, "time", SimpleNamespace(perf_counter=lambda: now))
    probe = timings.TimingProbe()
    with probe.collect(), timings.operation_label("lease_renew"):
        trace = timings.storage_trace()
        now = 12
        trace.advance("executor_wait")
        now = 15

        def work():
            nonlocal now
            now = 16
            with timings.sqlite_timing("sqlite_commit"):
                now = 21
                probe.interrupt(trace)
            probe.interrupt(trace)

        trace.run(work)
    during_commit, after_commit = probe.snapshot()["interruptions"]
    assert during_commit["operation"] == "lease_renew"
    assert during_commit["stage"] == "sqlite_commit"
    assert during_commit["elapsed_s"] == 11 and during_commit["stage_elapsed_s"] == 5
    assert during_commit["completed_stages_s"] == {
        "storage_serial_wait": 2,
        "storage_executor_wait": 3,
    }
    assert during_commit["commit_completion"]["wall_s"] == 5
    assert during_commit["commit_completion"]["worker_cpu_s"] >= 0
    assert during_commit["commit_completion"]["outcome"] == "returned"
    assert after_commit["stage"] == "operation" and after_commit["stage_elapsed_s"] == 6
    assert after_commit["completed_stages_s"]["sqlite_commit"] == 5
    assert "commit_completion" not in after_commit


async def test_interrupted_commit_preserves_busy_result_from_real_sqlite(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from stackchan_autonomy import state_store
    from stackchan_autonomy.timing_diagnostics import TimingProbe, operation_label

    path = tmp_path / "private-name.sqlite3"
    store = state_store.SQLiteState(path)
    with store.transaction():
        pass
    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute("BEGIN")
    assert reader.execute("SELECT count(*) FROM autonomy_clock").fetchone() == (0,)
    probe, storage = TimingProbe(), AsyncStorage()
    inside_commit = threading.Event()
    allow_commit = threading.Event()
    original_timing = state_store.sqlite_timing

    @contextmanager
    def observe(stage):
        with original_timing(stage):
            if stage == "sqlite_commit":
                inside_commit.set()
                assert allow_commit.wait(3)
            yield

    def write():
        with store.transaction() as db:
            store.observed_time(db, "private-scope", 1)

    monkeypatch.setattr(state_store, "sqlite_timing", observe)
    try:
        with probe.collect(), operation_label("lease_check"):
            task = asyncio.create_task(storage.call(write))
            await wait_thread(inside_commit)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert probe.snapshot()["interruptions"][-1]["commit_completion"] is None
            allow_commit.set()
            await storage.aclose()
    finally:
        allow_commit.set()
        reader.rollback()
        reader.close()
    record = probe.snapshot()["interruptions"][-1]
    assert record["stage"] == "sqlite_commit"
    assert record["completed_stages_s"]["sqlite_begin"] >= 0
    assert record["commit_completion"]["outcome"] == "busy"
    assert record["commit_completion"]["wall_s"] >= 0.15
    assert record["commit_completion"]["worker_cpu_s"] < record["commit_completion"]["wall_s"]
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM autonomy_clock").fetchone() == (0,)
    assert "private-" not in json.dumps(probe.snapshot())


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


@pytest.mark.parametrize("stall_delivery", [False, True], ids=["worker_running", "loop_stalled"])
async def test_measured_slow_lease_worker_still_fails_closed_without_retry(
    monkeypatch, stall_delivery
):
    from types import SimpleNamespace

    from stackchan_autonomy import action, soak
    from stackchan_autonomy.control import ControlLease
    from stackchan_autonomy.timing_diagnostics import StorageTrace, TimingProbe, _label

    original_lease_io = action.ActionExecutor._lease_io
    original_check = ControlLease.check
    original_advance = StorageTrace.advance
    original_interruption = TimingProbe.note_interruption
    loop = asyncio.get_running_loop()
    original_submit = loop.run_in_executor
    check_interrupted = threading.Event()
    check_started = threading.Event()
    check_ready = threading.Event()
    submission_observed = False
    calls = 0
    observation_delay = 0.0

    async def short_check_deadline(executor, operation, *args, extends=False):
        if operation == executor.lease.check:
            # Leave the cold acquisition at its normal validity. Give the
            # first verification a short remaining lifetime after setup.
            executor._authorized_until = action.time.monotonic() + 0.1
        return await original_lease_io(executor, operation, *args, extends=extends)

    def slow_check(self, handle):
        nonlocal calls
        calls += 1
        check_started.set()
        time.sleep(0.15)
        if not stall_delivery:
            # Keep the trace in the worker until the real lease deadline fires.
            assert check_interrupted.wait(3), "lease check interruption was not observed"
        return original_check(self, handle)

    def submit_with_check_barrier(executor, operation, *args):
        nonlocal observation_delay, submission_observed
        future = original_submit(executor, operation, *args)
        label = _label.get()
        if label == "lease_acquire":
            # Exercise late acquisition delivery without stalling the actual
            # loop monitor or altering the expiry written by real SQLite.
            observation_delay = 0.15
        if label == "lease_check":
            # Decide which point the worker reaches before the loop can run
            # the timeout callback. The submitted operation runs independently.
            observed = check_ready if stall_delivery else check_started
            submission_observed = observed.wait(3)
        return future

    def mark_stage(self, stage):
        original_advance(self, stage)
        if self.label == "lease_check" and stage == "delivery":
            check_ready.set()

    def record_interruption(self, label, stage, elapsed, **stage_timing):
        original_interruption(self, label, stage, elapsed, **stage_timing)
        if label == "lease_check":
            check_interrupted.set()

    monkeypatch.setattr(action.ActionExecutor, "_lease_io", short_check_deadline)
    monkeypatch.setattr(
        action, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + observation_delay)
    )
    monkeypatch.setattr(ControlLease, "check", slow_check)
    monkeypatch.setattr(loop, "run_in_executor", submit_with_check_barrier)
    if stall_delivery:
        monkeypatch.setattr(StorageTrace, "advance", mark_stage)
    else:
        monkeypatch.setattr(TimingProbe, "note_interruption", record_interruption)
    report = await soak.run_soak(soak.SoakConfig(cycles=8, warmup_cycles=1, diagnostics=True))
    assert not report.passed and "engine_failure" in report.violations
    assert report.failure.control_loss_reason in {"check_timeout", "renew_timeout"}
    assert report.failure.lease_lost and report.failure.action_stopped
    assert calls == 1 and report.cloud_requests == report.remaining_tasks == 0
    timing = report.timing_diagnostics
    assert timing["stages"]["storage_operation"]["max_s"] >= 0.14
    assert submission_observed
    expected = {"delivery", "post_delivery_deadline"} if stall_delivery else {"operation"}
    assert any(
        record["operation"] == "lease_check" and record["stage"] in expected
        for record in timing["interruptions"]
    ), timing["interruptions"]
    if stall_delivery:
        assert timing["loop_lag_max_s"] >= 0.04
