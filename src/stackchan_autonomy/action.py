"""Single command owner, with a latched stop and no automatic replay."""

import asyncio
import time

from pydantic import ValidationError

from .async_storage import AsyncStorage, finish_cleanup
from .control import ControlLease
from .models import ActionResult, ControlLossReason, Decision
from .ports import RobotAdapter
from .safety import SafetyPolicy, UnsafeDecision
from .settings import Settings
from .state_store import StateUnavailable


class ActionExecutor:
    def __init__(
        self,
        robot: RobotAdapter,
        settings: Settings,
        *,
        clock=time.monotonic,
        lease: ControlLease | None = None,
    ):
        self.robot = robot
        self.settings = settings
        self.policy = SafetyPolicy(settings)
        self.clock = clock
        self.stopped = False
        self.faulted = False
        self._last_key = None
        self._last_dispatch: float | None = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_size)
        self._worker: asyncio.Task | None = None
        self._active_future: asyncio.Future | None = None
        self.lease = lease or ControlLease(
            settings.state_path, settings.control_resource, ttl_s=settings.lease_ttl_s
        )
        self._lease_handle = None
        self._heartbeat: asyncio.Task | None = None
        self._storage = AsyncStorage()
        self._claim_lock = asyncio.Lock()
        self._close_task: asyncio.Task | None = None
        self.lease_lost = False
        self.control_loss_reason: ControlLossReason | None = None
        self.on_control_lost = None

    def _lose_control(self, reason: ControlLossReason = "lease_invalid"):
        if self.lease_lost:
            return
        self.control_loss_reason = reason
        self.lease_lost = self.faulted = True
        self.stop()
        if self.on_control_lost is not None:
            self.on_control_lost()

    def _acquire_lease(self):
        if self.stopped or self.faulted:
            return None
        # Retain a late result inside the tracked worker, even if its caller cancels.
        self._lease_handle = self.lease.acquire()
        return self._lease_handle

    async def _lease_io(self, operation, *args):
        # Include admission wait and commit latency; expiry is computed before commit.
        timeout = min(self.settings.operation_timeout_s, self.lease.ttl_s / 4)
        started = time.monotonic()
        async with asyncio.timeout(timeout):
            result = await self._storage.call(operation, *args)
        # A descheduled loop may deliver a ready result before its overdue timer.
        if time.monotonic() - started >= timeout:
            raise TimeoutError
        return result

    async def claim_control(self) -> bool:
        async with self._claim_lock:
            if self.stopped or self.faulted:
                return False
            acquiring = self._lease_handle is None
            try:
                if acquiring:
                    handle = await self._lease_io(self._acquire_lease)
                    if handle is None:
                        return False
                    if self.stopped or self.faulted:
                        return False
                    self._heartbeat = asyncio.create_task(
                        self._renew_control(), name="stackchan-lease-heartbeat"
                    )
                elif not await self._lease_io(self.lease.check, self._lease_handle):
                    self._lose_control()
                    return False
            except TimeoutError:
                if not self.stopped:
                    self._lose_control("acquire_timeout" if acquiring else "check_timeout")
                raise StateUnavailable("control verification timed out") from None
            except StateUnavailable:
                if self._lease_handle is not None and not self.stopped:
                    self._lose_control("verification_error")
                raise
            except asyncio.CancelledError:
                if not self.stopped:
                    self._lose_control("verification_cancelled")
                raise
            return not self.stopped and not self.faulted

    async def _renew_control(self):
        while not self.stopped:
            await asyncio.sleep(self.lease.ttl_s / 3)
            reason = "renew_rejected"
            try:
                renewed = await self._lease_io(self.lease.renew, self._lease_handle)
            except TimeoutError:
                renewed = False
                reason = "renew_timeout"
            except Exception:
                renewed = False
                reason = "renew_error"
            if not renewed:
                self._lose_control(reason)
                return

    async def execute(self, decision: Decision, *, explicit_request: bool = False) -> ActionResult:
        if self.faulted:
            return ActionResult(code="device_fault")
        if self.stopped:
            return ActionResult(code="stopped")
        future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait((decision, future, explicit_request))
        except asyncio.QueueFull:
            return ActionResult(code="queue_full")
        if self._worker is None:
            self._worker = asyncio.create_task(self._consume(), name="stackchan-action-owner")
        try:
            return await future
        except asyncio.CancelledError:
            if self._active_future is future:
                # The caller abandoning an active operation must not leave dispatch running.
                # A command might have reached the adapter already: require manual recovery.
                if not self.stopped:
                    self.faulted = True
                self.stop()
                if self._worker:
                    await asyncio.gather(self._worker, return_exceptions=True)
            raise

    def stop(self) -> None:
        self.stopped = True
        if self._worker:
            self._worker.cancel()
        if self._heartbeat and self._heartbeat is not asyncio.current_task():
            self._heartbeat.cancel()
        while not self._queue.empty():
            _, future, _ = self._queue.get_nowait()
            if not future.done():
                future.set_result(ActionResult(code="device_fault" if self.faulted else "stopped"))
            self._queue.task_done()

    async def aclose(self) -> None:
        self.stop()
        tasks = [
            t
            for t in (self._worker, self._heartbeat)
            if t is not None and t is not asyncio.current_task()
        ]
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(tasks), name="stackchan-action-cleanup"
            )
        await finish_cleanup(self._close_task)

    async def _close(self, tasks):
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self._storage.drain()
            if self._lease_handle is not None:
                try:
                    await self._storage.call(self.lease.release, self._lease_handle)
                except StateUnavailable:
                    pass  # Leave expiry in place; never erase another owner's lease.
                self._lease_handle = None
        finally:
            await self._storage.aclose()

    async def _consume(self) -> None:
        while True:
            decision, future, explicit_request = await self._queue.get()
            self._active_future = future
            try:
                if not future.cancelled():
                    result = await self._dispatch(decision, explicit_request=explicit_request)
                    if not future.done():
                        future.set_result(result)
            except asyncio.CancelledError:
                if not future.done():
                    future.set_result(ActionResult(code="stopped"))
                raise
            except Exception:
                # Decoder/custom adapter failures must resolve callers, never kill the owner.
                self.faulted = True
                if not future.done():
                    future.set_result(ActionResult(code="device_fault"))
            finally:
                self._active_future = None
                self._queue.task_done()

    async def _dispatch(
        self, decision: Decision, *, explicit_request: bool = False
    ) -> ActionResult:
        if self.stopped:
            return ActionResult(code="stopped")
        if self.faulted:
            return ActionResult(code="device_fault")
        try:
            # Read fresh absolute pose within the serial owner, not before queueing.
            async with asyncio.timeout(self.settings.operation_timeout_s):
                status = await self.robot.status()
                if not status.connected:
                    raise ConnectionError("disconnected")
                commands = self.policy.plan(decision, status)
                if self.stopped:
                    return ActionResult(code="stopped")
                if not commands:
                    return ActionResult()
                key = (
                    decision.intent,
                    decision.emotion,
                    decision.speech,
                    decision.yaw_delta_deg,
                    decision.pitch_delta_deg,
                )
                now = self.clock()
                duplicate = key == self._last_key
                if decision.intent == "speak":
                    duplicate = (
                        duplicate
                        and not explicit_request
                        and (
                            self._last_dispatch is not None
                            and now - self._last_dispatch < self.settings.speech_cooldown_s
                        )
                    )
                if duplicate:
                    return ActionResult(code="duplicate")
                if (
                    self._last_dispatch is not None
                    and now - self._last_dispatch < self.settings.command_interval_s
                ):
                    return ActionResult(code="command_rate_limit")
                if getattr(self.robot, "physical", True):
                    # Phase 4 deliberately cannot enable physical execution in this MVP.
                    return ActionResult(code="hardware_disabled")
                if not await self.claim_control():
                    return ActionResult(code="device_fault" if self.faulted else "lease_busy")
                self._last_key = key
                self._last_dispatch = now
                for command in commands:
                    if self.stopped:
                        return ActionResult(code="stopped")
                    if not await self.claim_control():
                        return ActionResult(code="device_fault" if self.faulted else "stopped")
                    if self.stopped or self.faulted:
                        return ActionResult(code="device_fault" if self.faulted else "stopped")
                    await self.robot.execute(command)
                return ActionResult(executed=True, code="executed")
        except (UnsafeDecision, ValidationError):
            return ActionResult(code="unsafe")
        except (ConnectionError, TimeoutError, OSError, RuntimeError):
            # Dispatch may already have reached the robot. Latch fault, never retry.
            self.faulted = True
            return ActionResult(code="device_fault")
