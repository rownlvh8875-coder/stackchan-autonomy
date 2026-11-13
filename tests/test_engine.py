import asyncio
import gc
import tracemalloc

from stackchan_autonomy.action import ActionExecutor
from stackchan_autonomy.decision import MockDecisionProvider
from stackchan_autonomy.engine import AutonomyEngine, EventQueue
from stackchan_autonomy.models import Decision, Event, EventKind, State
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


def settings(**overrides):
    return Settings(cooldown_s=0, command_interval_s=0, **overrides)


async def test_t1_complete_loop_and_t2_simulated_person_event():
    robot = FakeRobotAdapter(person_present=True)
    engine = AutonomyEngine(robot, MockDecisionProvider(), settings())
    try:
        result = await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert result.executed
        assert robot.history[-1].kind == "speak"
        assert engine.memory.recent()[-1].event == EventKind.PERSON_DETECTED
        assert list(engine.transitions)[:7] == [
            State.BOOT,
            State.IDLE,
            State.OBSERVE,
            State.THINK,
            State.VALIDATE,
            State.ACT,
            State.COOLDOWN,
        ]
        assert engine.state == State.IDLE
    finally:
        await engine.aclose()


async def test_t3_repeated_person_greeting_is_suppressed_until_cooldown():
    now = [1000.0]
    robot = FakeRobotAdapter(person_present=True)
    engine = AutonomyEngine(robot, MockDecisionProvider(), settings(), clock=lambda: now[0])
    try:
        await engine.step(Event(kind=EventKind.PERSON_DETECTED))
        now[0] += 30
        result = await engine.step(Event(kind=EventKind.PERSON_DETECTED))
        assert result.code == "speech_cooldown"
        assert len(robot.history) == 1
        # Change an expression so exact duplicate suppression and greeting cooldown are distinct.
        await engine.actions.execute(Decision(intent="emote", emotion="happy"))
        now[0] += 300
        result = await engine.step(Event(kind=EventKind.PERSON_DETECTED))
        assert result.executed
        assert len([c for c in robot.history if c.kind == "speak"]) == 2
    finally:
        await engine.aclose()


async def test_t4_invalid_ai_cannot_dispatch_motion():
    class BadAI:
        async def decide(self, observation, context):
            return Decision(intent="look", yaw_delta_deg=900)

    robot = FakeRobotAdapter()
    engine = AutonomyEngine(robot, BadAI(), settings())
    try:
        result = await engine.step(Event(kind=EventKind.TOUCH_TAP))
        assert result.code == "unsafe"
        assert not robot.history
    finally:
        await engine.aclose()


async def test_t5_provider_exception_and_timeout_safe_idle(caplog):
    class Unavailable:
        async def decide(self, observation, context):
            raise RuntimeError("secret-key-and-private-transcript")

    class Slow:
        async def decide(self, observation, context):
            await asyncio.Event().wait()

    for provider in (Unavailable(), Slow()):
        robot = FakeRobotAdapter()
        engine = AutonomyEngine(robot, provider, settings(operation_timeout_s=0.02))
        try:
            result = await engine.step(Event(kind=EventKind.TOUCH_TAP))
            assert result.code == "cycle_unavailable"
            assert not robot.history
            assert engine.state == State.IDLE
        finally:
            await engine.aclose()
    assert "secret-key-and-private-transcript" not in caplog.text


async def test_t6_ambiguous_disconnect_is_not_retried_after_reconnect():
    class LostAcknowledgement(FakeRobotAdapter):
        async def execute(self, command):
            await super().execute(command)
            raise ConnectionError("ACK lost after command may have executed")

    robot = LostAcknowledgement()
    executor = ActionExecutor(robot, settings())
    try:
        first = await executor.execute(Decision(intent="look", yaw_delta_deg=5))
        second = await executor.execute(Decision(intent="look", yaw_delta_deg=5))
        assert first.code == "device_fault"
        assert second.code == "device_fault"
        assert len(robot.history) == 1
    finally:
        await executor.aclose()


async def test_t7_stop_cancels_ai_and_blocks_all_later_actions():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class SlowAI:
        async def decide(self, observation, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    robot = FakeRobotAdapter()
    engine = AutonomyEngine(robot, SlowAI(), settings())
    cycle = asyncio.create_task(engine.step(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert engine.submit(Event(kind=EventKind.USER_STOP))
        await asyncio.wait_for(cancelled.wait(), 1)
        assert (await cycle).code == "stopped"
        assert not (await engine.actions.execute(Decision(intent="look", yaw_delta_deg=5))).executed
        assert engine.state == State.STOPPED
        assert not robot.history
    finally:
        await engine.aclose()


async def test_stop_cancels_inflight_command_and_drains_waiters():
    entered = asyncio.Event()

    class SlowRobot(FakeRobotAdapter):
        async def execute(self, command):
            entered.set()
            await asyncio.Event().wait()
            await super().execute(command)

    robot = SlowRobot()
    executor = ActionExecutor(robot, settings())
    first = asyncio.create_task(executor.execute(Decision(intent="look", yaw_delta_deg=5)))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(executor.execute(Decision(intent="emote", emotion="happy")))
    await asyncio.sleep(0)
    executor.stop()
    assert (await asyncio.wait_for(first, 1)).code == "stopped"
    assert (await asyncio.wait_for(second, 1)).code == "stopped"
    await executor.aclose()
    assert not robot.history


async def test_serial_commands_read_fresh_pose_and_drop_duplicate():
    active = 0
    maximum = 0

    class ProbeRobot(FakeRobotAdapter):
        async def execute(self, command):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            await super().execute(command)
            active -= 1

    robot = ProbeRobot()
    executor = ActionExecutor(robot, settings())
    try:
        results = await asyncio.gather(
            executor.execute(Decision(intent="look", yaw_delta_deg=5)),
            executor.execute(Decision(intent="look", yaw_delta_deg=10)),
            executor.execute(Decision(intent="look", yaw_delta_deg=10)),
        )
        assert [r.code for r in results] == ["executed", "executed", "duplicate"]
        assert [c.yaw for c in robot.history] == [5, 15]
        assert maximum == 1
    finally:
        await executor.aclose()


async def test_frequency_limit_does_not_delay_or_replay_commands():
    now = [0.0]
    robot = FakeRobotAdapter()
    executor = ActionExecutor(robot, Settings(command_interval_s=1), clock=lambda: now[0])
    try:
        await executor.execute(Decision(intent="look", yaw_delta_deg=5))
        result = await executor.execute(Decision(intent="emote", emotion="happy"))
        assert result.code == "command_rate_limit"
        now[0] = 1.1
        assert len(robot.history) == 1
    finally:
        await executor.aclose()


async def test_event_queue_prioritizes_user_and_evicts_timer_when_full():
    queue = EventQueue(2)
    assert queue.put(Event(kind=EventKind.TIMER_OBSERVE))
    assert queue.put(Event(kind=EventKind.SCENE_CHANGED))
    assert queue.put(Event(kind=EventKind.VOICE_REQUEST))
    assert (await queue.get()).kind == EventKind.VOICE_REQUEST
    assert (await queue.get()).kind == EventKind.SCENE_CHANGED


async def test_unchanged_timer_skips_decision_but_touch_bypasses_gate():
    class CounterAI(MockDecisionProvider):
        calls = 0

        async def decide(self, observation, context):
            self.calls += 1
            return await super().decide(observation, context)

    provider = CounterAI()
    engine = AutonomyEngine(FakeRobotAdapter(), provider, settings())
    try:
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert (await engine.step(Event(kind=EventKind.TIMER_OBSERVE))).code == "unchanged"
        await engine.step(Event(kind=EventKind.TOUCH_TAP))
        assert provider.calls == 2
    finally:
        await engine.aclose()


async def test_t10_bounded_histories_no_overlapping_tasks_under_1000_cycles():
    robot = FakeRobotAdapter(history_size=20)
    engine = AutonomyEngine(robot, MockDecisionProvider(), settings(history_size=20))
    baseline_tasks = len(asyncio.all_tasks())
    tracemalloc.start()
    try:
        for _ in range(100):
            result = await engine.step(robot.touch_event())
            assert result.code in {"executed", "speech_cooldown"}, (
                result.code,
                engine.actions.control_loss_reason,
            )
        gc.collect()
        baseline_memory = tracemalloc.get_traced_memory()[0]
        for _ in range(1000):
            result = await engine.step(robot.touch_event())
            assert result.code in {"executed", "speech_cooldown"}, (
                result.code,
                engine.actions.control_loss_reason,
            )
        gc.collect()
        growth = tracemalloc.get_traced_memory()[0] - baseline_memory
        assert len(engine.memory.recent()) <= 20
        assert len(engine.transitions) <= 20
        assert len(robot.history) <= 20
        # One action owner plus one renewable lease heartbeat, independent of cycle count.
        assert len(asyncio.all_tasks()) <= baseline_tasks + 2
        assert sum(t.get_name() == "stackchan-lease-heartbeat" for t in asyncio.all_tasks()) == 1
        assert growth < 1_000_000
    finally:
        tracemalloc.stop()
        await engine.aclose()
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) <= baseline_tasks


async def test_scheduler_runs_then_stops_without_leftover_tasks(monkeypatch):
    engine = AutonomyEngine(
        FakeRobotAdapter(), MockDecisionProvider(), settings(observe_interval_s=0.01)
    )
    recorded = asyncio.Event()
    loop = asyncio.get_running_loop()
    original_record = engine.memory.record

    def record(*args, **kwargs):
        original_record(*args, **kwargs)
        loop.call_soon_threadsafe(recorded.set)

    monkeypatch.setattr(engine.memory, "record", record)
    run = asyncio.create_task(engine.run())
    completed = asyncio.create_task(recorded.wait())
    try:
        done, _ = await asyncio.wait(
            (run, completed), timeout=20, return_when=asyncio.FIRST_COMPLETED
        )
        assert completed in done, (engine.state, engine.actions.control_loss_reason)
        assert await engine.memory_recent()
        engine.stop()
        await asyncio.wait_for(run, 3)
    finally:
        completed.cancel()
        await asyncio.gather(completed, return_exceptions=True)
        await engine.aclose()
