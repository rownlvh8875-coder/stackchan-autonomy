import asyncio

import pytest

from stackchan_autonomy.action import ActionExecutor
from stackchan_autonomy.engine import AutonomyEngine
from stackchan_autonomy.models import Decision, Event, EventKind
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


async def test_cycle_timeout_cannot_leave_background_action_running():
    class SlowRobot(FakeRobotAdapter):
        async def capture(self):
            await asyncio.sleep(0.05)
            return await super().capture()

        async def execute(self, command):
            await asyncio.sleep(0.06)
            await super().execute(command)

    class LookAI:
        async def decide(self, observation, context):
            return Decision(intent="look", yaw_delta_deg=5)

    robot = SlowRobot()
    engine = AutonomyEngine(robot, LookAI(), Settings(operation_timeout_s=0.08, cooldown_s=0))
    try:
        result = await engine.step(Event(kind=EventKind.TOUCH_TAP))
        assert not result.executed
        await asyncio.sleep(0.1)
        assert not robot.history
        assert engine.actions.faulted
    finally:
        await engine.aclose()


async def test_cancelled_request_before_send_never_dispatches():
    entered = asyncio.Event()

    class SlowStatus(FakeRobotAdapter):
        async def status(self):
            entered.set()
            await asyncio.sleep(0.05)
            return await super().status()

    robot = SlowStatus()
    executor = ActionExecutor(robot, Settings())
    try:
        task = asyncio.create_task(executor.execute(Decision(intent="look", yaw_delta_deg=5)))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.08)
        assert not robot.history
        assert executor.faulted
    finally:
        await executor.aclose()


async def test_unexpected_adapter_exception_resolves_all_requests_and_faults():
    class BrokenStatus(FakeRobotAdapter):
        async def status(self):
            raise ValueError("private malformed device response")

    executor = ActionExecutor(BrokenStatus(), Settings(command_interval_s=0))
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                executor.execute(Decision(intent="look", yaw_delta_deg=5)),
                executor.execute(Decision(intent="emote", emotion="happy")),
            ),
            0.2,
        )
        assert [r.code for r in results] == ["device_fault", "device_fault"]
        assert executor.faulted
    finally:
        await executor.aclose()


async def test_person_detection_preserves_higher_priority_voice_text():
    seen = []

    class InspectAI:
        async def decide(self, observation, context):
            seen.append(context.event)
            return Decision()

    engine = AutonomyEngine(
        FakeRobotAdapter(person_present=True), InspectAI(), Settings(cooldown_s=0)
    )
    try:
        await engine.step(Event(kind=EventKind.VOICE_REQUEST, text="왼쪽을 봐 주세요"))
        assert seen[0].kind == EventKind.VOICE_REQUEST
        assert seen[0].text == "왼쪽을 봐 주세요"
    finally:
        await engine.aclose()


async def test_unchanged_scene_retries_after_analysis_failure():
    class RecoveringAI:
        calls = 0

        async def decide(self, observation, context):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("transient")
            return Decision(intent="emote", emotion="happy")

    provider = RecoveringAI()
    engine = AutonomyEngine(FakeRobotAdapter(), provider, Settings(cooldown_s=0))
    try:
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        second = await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert second.executed
        assert provider.calls == 2
    finally:
        await engine.aclose()


async def test_duplicate_speech_expires_but_motor_replay_remains_blocked():
    now = [0.0]
    robot = FakeRobotAdapter()
    executor = ActionExecutor(
        robot, Settings(command_interval_s=0, speech_cooldown_s=300), clock=lambda: now[0]
    )
    try:
        speech = Decision(intent="speak", speech="안녕하세요")
        assert (await executor.execute(speech)).executed
        assert (await executor.execute(speech)).code == "duplicate"
        now[0] = 301
        assert (await executor.execute(speech)).executed
        move = Decision(intent="look", yaw_delta_deg=5)
        assert (await executor.execute(move)).executed
        now[0] = 900
        assert (await executor.execute(move)).code == "duplicate"
    finally:
        await executor.aclose()


async def test_explicit_voice_request_can_repeat_answer_without_auto_greeting_gate():
    class AnswerAI:
        async def decide(self, observation, context):
            return Decision(intent="speak", speech="네, 듣고 있어요.")

    robot = FakeRobotAdapter()
    engine = AutonomyEngine(robot, AnswerAI(), Settings(cooldown_s=0, command_interval_s=0))
    try:
        for _ in range(2):
            result = await engine.step(Event(kind=EventKind.VOICE_REQUEST, text="듣고 있니?"))
            assert result.executed
        assert len(robot.history) == 2
    finally:
        await engine.aclose()


async def test_unchanged_scene_is_reanalyzed_after_bounded_interval():
    now = [0.0]

    class CounterAI:
        calls = 0

        async def decide(self, observation, context):
            self.calls += 1
            return Decision()

    provider = CounterAI()
    engine = AutonomyEngine(
        FakeRobotAdapter(), provider, Settings(cooldown_s=0), clock=lambda: now[0]
    )
    try:
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        now[0] = 30
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert provider.calls == 1
        now[0] = 301
        await engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert provider.calls == 2
    finally:
        await engine.aclose()
