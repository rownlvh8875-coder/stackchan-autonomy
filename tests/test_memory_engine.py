import sqlite3

import pytest

from stackchan_autonomy.decision import MockDecisionProvider
from stackchan_autonomy.engine import AutonomyEngine
from stackchan_autonomy.memory import Memory
from stackchan_autonomy.models import Decision, Event, EventKind, RobotStatus, State
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


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
