import asyncio
import sqlite3
import threading

import pytest

from stackchan_autonomy.decision import MockDecisionProvider
from stackchan_autonomy.engine import AutonomyEngine
from stackchan_autonomy.memory import Memory
from stackchan_autonomy.models import Decision, Event, EventKind, RobotStatus, State
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


async def test_file_memory_wait_allows_real_control_heartbeat_to_progress(monkeypatch, tmp_path):
    engine = AutonomyEngine(
        FakeRobotAdapter(),
        MockDecisionProvider(),
        settings(tmp_path / "slow-memory.sqlite3", lease_ttl_s=2, operation_timeout_s=5),
    )
    waiting, renewed, release = threading.Event(), threading.Event(), threading.Event()
    original_snapshot = engine.memory.snapshot
    original_renew = engine.actions.lease.renew

    def slow_snapshot():
        waiting.set()
        release.wait(3)  # Simulate a slow file call without changing lease/engine clocks.
        return original_snapshot()

    def renewal_during_storage_wait(handle):
        result = original_renew(handle)  # Real SQLite expiry/ownership checks remain active.
        if waiting.is_set():
            if result:
                renewed.set()
            release.set()
        return result

    try:
        assert (await engine.step(Event(kind=EventKind.VOICE_REQUEST))).executed
        monkeypatch.setattr(engine.memory, "snapshot", slow_snapshot)
        monkeypatch.setattr(engine.actions.lease, "renew", renewal_during_storage_wait)
        result = await engine.step(Event(kind=EventKind.VOICE_REQUEST))
        assert renewed.is_set(), "file-backed memory blocked the control heartbeat"
        assert result.executed and not engine.actions.lease_lost
    finally:
        release.set()
        await engine.aclose()


async def test_stop_during_file_read_blocks_dispatch_and_close_waits_for_io(monkeypatch, tmp_path):
    engine = AutonomyEngine(
        FakeRobotAdapter(), MockDecisionProvider(), settings(tmp_path / "closing.sqlite3")
    )
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    closed_too_soon = []
    original_snapshot, original_close = engine.memory.snapshot, engine.memory.close

    def slow_snapshot():
        started.set()
        release.wait(3)
        try:
            return original_snapshot()
        finally:
            finished.set()

    def close():
        if not finished.is_set():
            closed_too_soon.append(True)
        original_close()

    monkeypatch.setattr(engine.memory, "snapshot", slow_snapshot)
    monkeypatch.setattr(engine.memory, "close", close)
    cycle = asyncio.create_task(engine.step(Event(kind=EventKind.VOICE_REQUEST)))
    closer = None
    try:
        async with asyncio.timeout(4):
            while not started.is_set():
                await asyncio.sleep(0.001)
        engine.stop()
        assert (await cycle).code == "stopped"
        assert not engine.robot.history
        closer = asyncio.create_task(engine.aclose())
        await asyncio.sleep(0.02)
        assert not closer.done(), "cleanup abandoned an active file operation"
        closer.cancel()
        await asyncio.sleep(0)
        closer.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert finished.is_set() and not closed_too_soon
        assert not engine.robot.history
    finally:
        release.set()
        await asyncio.gather(cycle, *([closer] if closer else []), return_exceptions=True)
        await engine.aclose()


async def test_file_io_timeout_faults_instead_of_starting_another_cycle(monkeypatch, tmp_path):
    engine = AutonomyEngine(
        FakeRobotAdapter(),
        MockDecisionProvider(),
        settings(tmp_path / "timeout.sqlite3", operation_timeout_s=0.1),
    )
    started, release = threading.Event(), threading.Event()
    original = engine.memory.recent
    calls = []

    def blocked_recent():
        calls.append(1)
        started.set()
        release.wait(2)
        return original()

    monkeypatch.setattr(engine.memory, "recent", blocked_recent)
    try:
        result = await engine.step(Event(kind=EventKind.VOICE_REQUEST))
        assert result.code == "cycle_unavailable" and engine.state == State.ERROR
        assert (await engine.step(Event(kind=EventKind.VOICE_REQUEST))).code == "stopped"
        assert calls == [1] and not engine.robot.history
    finally:
        release.set()
        await engine.aclose()


def settings(path, **overrides):
    return Settings(memory_path=path, cooldown_s=0, command_interval_s=0, **overrides)


async def test_restart_respects_speech_cooldown_after_recent_history_eviction(tmp_path):
    path = tmp_path / "restart.sqlite3"
    first = AutonomyEngine(
        FakeRobotAdapter(), MockDecisionProvider(), settings(path), clock=lambda: 1000
    )
    try:
        assert (await first.step(Event(kind=EventKind.TOUCH_TAP))).executed
        for _ in range(105):
            first.memory.record(1001, EventKind.TIMER_OBSERVE, "idle", "idle")
    finally:
        await first.aclose()
    robot = FakeRobotAdapter(person_present=True)
    second = AutonomyEngine(robot, MockDecisionProvider(), settings(path), clock=lambda: 1030)
    try:
        assert (await second.step(Event(kind=EventKind.TIMER_OBSERVE))).code == "speech_cooldown"
        assert not robot.history
    finally:
        await second.aclose()


async def test_updated_preferences_disable_background_speech_but_keep_touch_and_voice(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    engine = AutonomyEngine(
        FakeRobotAdapter(person_present=True),
        MockDecisionProvider(),
        settings(path),
        clock=lambda: 1000,
    )
    try:
        with Memory(path=path, clock=lambda: 1000) as editor:
            editor.update_preferences(automatic_speech_enabled=False)
        assert (
            await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        ).code == "automatic_speech_disabled"
        assert not engine.robot.history
        assert (await engine.step(Event(kind=EventKind.TOUCH_TAP))).executed
        assert (await engine.step(Event(kind=EventKind.VOICE_REQUEST, text="private"))).executed
        assert b"private" not in path.read_bytes()
    finally:
        await engine.aclose()


@pytest.mark.parametrize("configured,preferred", [(300, 600), (600, 0)])
async def test_preference_can_increase_but_not_reduce_configured_cooldown(
    tmp_path, configured, preferred
):
    path = tmp_path / "interval.sqlite3"
    with Memory(path=path, clock=lambda: 1000) as memory:
        memory.update_preferences(minimum_speech_interval_s=preferred)
        memory.record(1000, EventKind.PERSON_DETECTED, "speak", "executed")
    engine = AutonomyEngine(
        FakeRobotAdapter(person_present=True),
        MockDecisionProvider(),
        settings(path, speech_cooldown_s=configured),
        clock=lambda: 1400,
    )
    try:
        assert (await engine.step(Event(kind=EventKind.TIMER_OBSERVE))).code == "speech_cooldown"
        assert (await engine.step(Event(kind=EventKind.VOICE_REQUEST))).executed
    finally:
        await engine.aclose()


async def test_corrupted_memory_stops_before_dispatch_without_private_error(caplog, tmp_path):
    path = tmp_path / "bad.sqlite3"
    engine = AutonomyEngine(FakeRobotAdapter(), MockDecisionProvider(), settings(path))
    try:
        path.write_bytes(b"private-transcript-corrupt-db")
        assert (await engine.step(Event(kind=EventKind.TOUCH_TAP))).code == "memory_unavailable"
        assert engine.state == State.ERROR and engine.stop_event.is_set()
        assert not engine.robot.history
        assert "private-transcript" not in caplog.text
    finally:
        await engine.aclose()


async def test_storage_failure_after_dispatch_stops_without_replaying(tmp_path):
    path = tmp_path / "late-failure.sqlite3"
    held = sqlite3.connect(path)

    class LockAfterAction(FakeRobotAdapter):
        async def execute(self, command):
            await super().execute(command)
            held.execute("BEGIN IMMEDIATE")

    engine = AutonomyEngine(LockAfterAction(), MockDecisionProvider(), settings(path))
    try:
        assert (await engine.step(Event(kind=EventKind.TOUCH_TAP))).code == "memory_unavailable"
        assert engine.state == State.ERROR and engine.stop_event.is_set()
        assert len(engine.robot.history) == 1
        assert (await engine.step(Event(kind=EventKind.TOUCH_TAP))).code == "stopped"
        assert len(engine.robot.history) == 1
    finally:
        held.rollback()
        held.close()
        await engine.aclose()


async def test_historical_pose_is_only_observed_metadata_and_is_not_restored(tmp_path):
    path = tmp_path / "pose.sqlite3"
    with Memory(path=path, clock=lambda: 1000) as memory:
        memory.record(
            999, EventKind.TIMER_OBSERVE, "idle", "idle", status=RobotStatus(yaw=50, pitch=80)
        )
    robot = FakeRobotAdapter()
    engine = AutonomyEngine(robot, MockDecisionProvider(), settings(path), clock=lambda: 1000)
    try:
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert (await robot.status()).yaw == 0
        assert (await robot.status()).pitch == 45
        assert all(command.kind != "move" for command in robot.history)
        assert engine.memory.snapshot().robot.yaw == 0
    finally:
        await engine.aclose()


async def test_speech_completion_and_pose_observation_have_distinct_timestamps(tmp_path):
    now = [1000]

    class SlowSpeech(FakeRobotAdapter):
        async def execute(self, command):
            await super().execute(command)
            now[0] = 1010

    engine = AutonomyEngine(
        SlowSpeech(),
        MockDecisionProvider(),
        settings(tmp_path / "times.sqlite3"),
        clock=lambda: now[0],
    )
    try:
        await engine.step(Event(kind=EventKind.TOUCH_TAP))
        snapshot = engine.memory.snapshot()
        assert snapshot.last_spoken_at == 1010
        assert snapshot.robot.at == 1000
    finally:
        await engine.aclose()


def test_persistent_memory_retention_must_cover_configured_cooldown(tmp_path):
    with pytest.raises(ValueError):
        settings(tmp_path / "short.sqlite3", memory_retention_s=60, speech_cooldown_s=300)


def test_in_memory_retention_must_also_cover_configured_cooldown():
    with pytest.raises(ValueError):
        Settings(memory_path=None, memory_retention_s=60, speech_cooldown_s=300)


async def test_large_clock_rollback_preserves_suppression_for_new_speech(tmp_path):
    now = [1000]

    class DifferentSpeech:
        count = 0

        async def decide(self, observation, context):
            self.count += 1
            return Decision(intent="speak", speech=f"fixture {self.count}")

    engine = AutonomyEngine(
        FakeRobotAdapter(),
        DifferentSpeech(),
        settings(tmp_path / "rollback.sqlite3", memory_retention_s=60, speech_cooldown_s=60),
        clock=lambda: now[0],
    )
    try:
        now[0] = 100
        assert (await engine.step(Event(kind=EventKind.VOICE_REQUEST))).executed
        assert (await engine.step(Event(kind=EventKind.PERSON_DETECTED))).code == "speech_cooldown"
        assert len(engine.robot.history) == 1
        # Retain a logical suppression clock; do not relabel expired raw wall-time history.
        snapshot = engine.memory.snapshot()
        assert snapshot.last_speech_guard_at == 1000
        assert snapshot.last_spoken_at is None
        assert snapshot.recent == ()
    finally:
        await engine.aclose()
