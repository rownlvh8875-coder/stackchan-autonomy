import asyncio
import os
import subprocess
import sys

import pytest

from stackchan_autonomy.action import ActionExecutor
from stackchan_autonomy.control import ControlLease
from stackchan_autonomy.models import Decision
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


async def test_two_executors_cannot_dispatch_same_resource_until_release():
    settings = Settings(command_interval_s=0)
    first_robot, second_robot = FakeRobotAdapter(), FakeRobotAdapter()
    first = ActionExecutor(first_robot, settings)
    second = ActionExecutor(second_robot, settings)
    try:
        assert (await first.execute(Decision(intent="look", yaw_delta_deg=5))).executed
        assert (await second.execute(Decision(intent="look", yaw_delta_deg=5))).code == "lease_busy"
        assert not second_robot.history
        await first.aclose()
        assert (await second.execute(Decision(intent="look", yaw_delta_deg=5))).executed
    finally:
        await first.aclose()
        await second.aclose()


async def test_live_heartbeat_renews_ownership_until_close():
    settings = Settings(lease_ttl_s=0.15, command_interval_s=0)
    executor = ActionExecutor(FakeRobotAdapter(), settings)
    contender = ControlLease(settings.state_path, settings.control_resource, ttl_s=0.15)
    try:
        assert await executor.claim_control()
        await asyncio.sleep(0.35)
        assert contender.acquire() is None
    finally:
        await executor.aclose()
    assert contender.acquire() is not None


async def test_lease_expiry_blocks_next_command_without_reacquisition():
    now = [100.0]
    settings = Settings(command_interval_s=0, lease_ttl_s=0.2)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=0.2, clock=lambda: now[0]
    )
    robot = FakeRobotAdapter()
    executor = ActionExecutor(robot, settings, lease=lease)
    try:
        assert (await executor.execute(Decision(intent="look", yaw_delta_deg=5))).executed
        now[0] = 101
        result = await executor.execute(Decision(intent="emote", emotion="happy"))
        assert not result.executed
        assert executor.faulted
        assert len(robot.history) == 1
    finally:
        await executor.aclose()


async def test_lease_loss_cancels_active_local_work_and_blocks_queued_commands():
    now = [100.0]
    entered = asyncio.Event()

    class SlowRobot(FakeRobotAdapter):
        async def execute(self, command):
            entered.set()
            await asyncio.Event().wait()
            await super().execute(command)

    settings = Settings(command_interval_s=0, lease_ttl_s=0.15)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=0.15, clock=lambda: now[0]
    )
    robot = SlowRobot()
    executor = ActionExecutor(robot, settings, lease=lease)
    first = asyncio.create_task(executor.execute(Decision(intent="look", yaw_delta_deg=5)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(executor.execute(Decision(intent="emote", emotion="happy")))
        now[0] = 101
        await asyncio.wait_for(first, 1)
        assert not (await asyncio.wait_for(second, 1)).executed
        assert executor.faulted
        assert not robot.history
    finally:
        await executor.aclose()


async def test_storage_failure_does_not_fall_back_to_unleased_commands():
    settings = Settings(command_interval_s=0)
    settings.state_path.write_bytes(b"corrupt sqlite")
    robot = FakeRobotAdapter()
    executor = ActionExecutor(robot, settings)
    try:
        result = await executor.execute(Decision(intent="look", yaw_delta_deg=5))
        assert not result.executed
        assert executor.faulted
        assert not robot.history
    finally:
        await executor.aclose()


@pytest.mark.parametrize("mode", ["mock", "mcp-sim"])
async def test_cli_refuses_control_held_by_another_process(mode):
    script = """
import json
from stackchan_autonomy.control import ControlLease
from stackchan_autonomy.settings import Settings
s=Settings()
held=ControlLease(s.state_path,s.control_resource).acquire()
assert held
print('held',flush=True)
"""
    # Abrupt normal process exit without release: ownership remains until TTL.
    held = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert held.returncode == 0, held.stderr
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "stackchan_autonomy", "--mode", mode, "--cycles", "1"],
        env=dict(os.environ),
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert "control" in result.stderr.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("mode", ["mock", "mcp-sim"])
def test_cli_storage_error_has_a_clear_message_without_traceback(mode):
    settings = Settings()
    settings.state_path.write_bytes(b"invalid db")
    result = subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy", "--mode", mode, "--cycles", "1"],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert "storage" in result.stderr.lower()
    assert "Traceback" not in result.stderr


async def test_close_removes_heartbeat_and_releases_after_cancelled_work():
    baseline = len(asyncio.all_tasks())
    settings = Settings()
    executor = ActionExecutor(FakeRobotAdapter(), settings)
    assert await executor.claim_control()
    await executor.aclose()
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == baseline
    assert ControlLease(settings.state_path, settings.control_resource).acquire() is not None


async def test_lease_loss_stops_idle_engine_before_next_observation():
    from stackchan_autonomy.decision import MockDecisionProvider
    from stackchan_autonomy.engine import AutonomyEngine
    from stackchan_autonomy.models import State

    now = [100.0]
    acted = asyncio.Event()

    class NotifyingRobot(FakeRobotAdapter):
        async def execute(self, command):
            await super().execute(command)
            acted.set()

    settings = Settings(lease_ttl_s=0.15, observe_interval_s=60, cooldown_s=0)
    engine = AutonomyEngine(NotifyingRobot(), MockDecisionProvider(), settings)
    engine.actions.lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=0.15, clock=lambda: now[0]
    )
    task = asyncio.create_task(engine.run())
    try:
        await asyncio.wait_for(acted.wait(), 1)
        now[0] = 101
        await asyncio.wait_for(task, 0.5)
        assert engine.state == State.ERROR
        assert engine.actions.faulted
    finally:
        await engine.aclose()
