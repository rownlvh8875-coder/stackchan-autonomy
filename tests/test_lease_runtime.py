import asyncio
import os
import subprocess
import sys
import threading
import time

import pytest

from stackchan_autonomy.action import ActionExecutor
from stackchan_autonomy.control import ControlLease
from stackchan_autonomy.models import Decision
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings


async def test_control_deadline_is_checked_even_if_loop_cannot_schedule_timer(monkeypatch):
    from types import SimpleNamespace

    from stackchan_autonomy import action
    from stackchan_autonomy.state_store import StateUnavailable

    executor = ActionExecutor(FakeRobotAdapter(), Settings(lease_ttl_s=1.5))
    assert await executor.claim_control()
    offset = [0.0]
    original_call = executor._storage.call

    async def delayed_delivery(*args, **kwargs):
        value = await original_call(*args, **kwargs)
        offset[0] += 2  # Model a descheduled loop after the DB result is ready.
        return value

    monkeypatch.setattr(
        action, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + offset[0])
    )
    monkeypatch.setattr(executor._storage, "call", delayed_delivery)
    try:
        with pytest.raises(StateUnavailable):
            await executor.claim_control()
        assert executor.control_loss_reason == "check_timeout"
        assert not executor.robot.history
    finally:
        monkeypatch.setattr(executor._storage, "call", original_call)
        await executor.aclose()


async def test_cold_unowned_acquisition_can_return_fresh_lease_after_slow_setup(monkeypatch):
    executor = ActionExecutor(FakeRobotAdapter(), Settings(lease_ttl_s=1.5))
    original = executor.lease.acquire

    def cold_acquire():
        time.sleep(2)  # Before the DB computes the lease timestamp; no ownership yet.
        return original()

    monkeypatch.setattr(executor.lease, "acquire", cold_acquire)
    try:
        assert await executor.claim_control()
        assert not executor.faulted
    finally:
        await executor.aclose()


async def test_valid_verification_uses_remaining_lifetime_not_a_fixed_fraction(monkeypatch):
    executor = ActionExecutor(FakeRobotAdapter(), Settings(lease_ttl_s=1.5))
    assert await executor.claim_control()
    original = executor.lease.check

    def delayed_check(handle):
        result = original(handle)
        time.sleep(0.6)  # Longer than TTL/4, still within the verified live lease.
        return result

    monkeypatch.setattr(executor.lease, "check", delayed_check)
    try:
        assert await executor.claim_control()
        assert not executor.faulted
    finally:
        await executor.aclose()


async def test_heartbeat_schedules_from_remaining_lifetime_after_slow_acquire(monkeypatch):
    settings = Settings(lease_ttl_s=1.5)
    executor = ActionExecutor(FakeRobotAdapter(), settings)
    original = executor.lease.acquire

    def slow_commit_delivery():
        handle = original()
        time.sleep(1)  # Only about0.5s of this lease remains when the caller sees it.
        return handle

    monkeypatch.setattr(executor.lease, "acquire", slow_commit_delivery)
    try:
        assert await executor.claim_control()
        await asyncio.sleep(1)
        assert not executor.faulted
        contender = ControlLease(settings.state_path, settings.control_resource)
        assert contender.acquire() is None
    finally:
        await executor.aclose()


async def test_cancelled_slow_acquire_is_drained_and_its_late_handle_released(monkeypatch):
    settings = Settings(command_interval_s=0)
    executor = ActionExecutor(FakeRobotAdapter(), settings)
    started, release = threading.Event(), threading.Event()
    original = executor.lease.acquire

    def blocked_acquire():
        started.set()
        release.wait(3)
        return original()

    monkeypatch.setattr(executor.lease, "acquire", blocked_acquire)
    claim = asyncio.create_task(executor.claim_control())
    closer = None
    try:
        async with asyncio.timeout(4):
            while not started.is_set():
                await asyncio.sleep(0.001)
        claim.cancel()
        with pytest.raises(asyncio.CancelledError):
            await claim
        assert executor.faulted
        closer = asyncio.create_task(executor.aclose())
        await asyncio.sleep(0.02)
        assert not closer.done()
        release.set()
        await closer
        assert not executor.robot.history
        contender = ControlLease(settings.state_path, settings.control_resource)
        assert contender.acquire() is not None
    finally:
        release.set()
        await asyncio.gather(claim, *([closer] if closer else []), return_exceptions=True)
        await executor.aclose()


async def test_stop_during_successful_verification_cannot_dispatch(monkeypatch):
    executor = ActionExecutor(FakeRobotAdapter(), Settings(command_interval_s=0))
    assert await executor.claim_control()
    started, release = threading.Event(), threading.Event()
    original = executor.lease.check

    def blocked_check(handle):
        started.set()
        release.wait(3)
        return original(handle)

    monkeypatch.setattr(executor.lease, "check", blocked_check)
    operation = asyncio.create_task(executor.execute(Decision(intent="look", yaw_delta_deg=5)))
    try:
        async with asyncio.timeout(4):
            while not started.is_set():
                await asyncio.sleep(0.001)
        executor.stop()
        release.set()
        assert not (await operation).executed
        assert not executor.robot.history
    finally:
        release.set()
        await asyncio.gather(operation, return_exceptions=True)
        await executor.aclose()


async def test_delayed_successful_renewal_times_out_and_cannot_clear_fault(monkeypatch):
    settings = Settings(command_interval_s=0, lease_ttl_s=1.5)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=1.5, clock=lambda: 100
    )
    executor = ActionExecutor(FakeRobotAdapter(), settings, lease=lease)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = lease.renew

    def blocked_renew(handle):
        started.set()
        release.wait(4)
        try:
            return original(handle)  # Frozen lease clock permits a deliberately late True.
        finally:
            finished.set()

    monkeypatch.setattr(lease, "renew", blocked_renew)
    try:
        assert await executor.claim_control()
        async with asyncio.timeout(5):
            while not executor.faulted:
                await asyncio.sleep(0.005)
        assert started.is_set() and not finished.is_set(), "renewal blocked the fault deadline"
        assert not (await executor.execute(Decision(intent="look", yaw_delta_deg=5))).executed
        release.set()
        await executor.aclose()
        assert finished.is_set() and executor.faulted and executor.lease_lost
        assert not executor.robot.history
    finally:
        release.set()
        await executor.aclose()


@pytest.mark.parametrize("phase", ["acquire", "check"])
async def test_late_successful_control_io_cannot_authorize_dispatch(monkeypatch, phase):
    settings = Settings(command_interval_s=0, lease_ttl_s=1.5)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=1.5, clock=lambda: 100
    )
    executor = ActionExecutor(FakeRobotAdapter(), settings, lease=lease)
    if phase == "check":
        assert await executor.claim_control()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = getattr(lease, phase)

    def blocked(*args):
        started.set()
        result = original(*args)
        release.wait(2)  # Delay delivery after the lease was actually verified.
        try:
            return result
        finally:
            finished.set()

    monkeypatch.setattr(lease, phase, blocked)
    try:
        result = await executor.execute(Decision(intent="look", yaw_delta_deg=5))
        assert not result.executed and not executor.robot.history
        assert executor.faulted
        if phase == "check":
            assert not finished.is_set()
        assert executor.control_loss_reason == phase + "_timeout"
        release.set()
        await executor.aclose()
        assert finished.is_set()
        assert ControlLease(settings.state_path, settings.control_resource).acquire() is not None
    finally:
        release.set()
        await executor.aclose()


@pytest.mark.parametrize("phase", ["acquire", "check"])
async def test_stopped_direct_claim_cannot_return_permission(monkeypatch, phase):
    executor = ActionExecutor(FakeRobotAdapter(), Settings(command_interval_s=0))
    if phase == "check":
        assert await executor.claim_control()
    started, release = threading.Event(), threading.Event()
    original = getattr(executor.lease, phase)

    def blocked(*args):
        started.set()
        release.wait(2)
        return original(*args)

    monkeypatch.setattr(executor.lease, phase, blocked)
    task = asyncio.create_task(executor.claim_control())
    try:
        async with asyncio.timeout(3):
            while not started.is_set():
                await asyncio.sleep(0.001)
        executor.stop()
        release.set()
        assert not await task
        assert not executor.robot.history
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await executor.aclose()


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
    settings = Settings(lease_ttl_s=1.5, command_interval_s=0)
    executor = ActionExecutor(FakeRobotAdapter(), settings)
    contender = ControlLease(settings.state_path, settings.control_resource, ttl_s=1.5)
    try:
        assert await executor.claim_control()
        await asyncio.sleep(3.2)  # Longer than the initial lease, independent of disk speed.
        assert contender.acquire() is None
    finally:
        await executor.aclose()
    assert contender.acquire() is not None


async def test_lease_expiry_blocks_next_command_without_reacquisition():
    now = [100.0]
    settings = Settings(command_interval_s=0, lease_ttl_s=1.5)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=1.5, clock=lambda: now[0]
    )
    robot = FakeRobotAdapter()
    executor = ActionExecutor(robot, settings, lease=lease)
    try:
        assert (await executor.execute(Decision(intent="look", yaw_delta_deg=5))).executed
        now[0] = 103
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

    settings = Settings(command_interval_s=0, lease_ttl_s=1.5)
    lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=1.5, clock=lambda: now[0]
    )
    robot = SlowRobot()
    executor = ActionExecutor(robot, settings, lease=lease)
    first = asyncio.create_task(executor.execute(Decision(intent="look", yaw_delta_deg=5)))
    try:
        await asyncio.wait_for(entered.wait(), 20)
        second = asyncio.create_task(executor.execute(Decision(intent="emote", emotion="happy")))
        now[0] = 103
        await asyncio.wait_for(first, 3)
        assert not (await asyncio.wait_for(second, 3)).executed
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

    settings = Settings(lease_ttl_s=1.5, observe_interval_s=60, cooldown_s=0)
    engine = AutonomyEngine(NotifyingRobot(), MockDecisionProvider(), settings)
    engine.actions.lease = ControlLease(
        settings.state_path, settings.control_resource, ttl_s=1.5, clock=lambda: now[0]
    )
    task = asyncio.create_task(engine.run())
    try:
        await asyncio.wait_for(acted.wait(), 20)
        now[0] = 103
        await asyncio.wait_for(task, 3)
        assert engine.state == State.ERROR
        assert engine.actions.faulted
    finally:
        await engine.aclose()
