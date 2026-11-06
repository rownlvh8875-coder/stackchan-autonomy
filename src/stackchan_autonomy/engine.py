import asyncio
import heapq
import itertools
import logging
import time
from collections import deque

from .action import ActionExecutor
from .memory import Memory
from .models import ActionResult, Decision, DecisionContext, Event, EventKind, State
from .perception import Perception
from .ports import DecisionProvider, RobotAdapter
from .settings import Settings

logger = logging.getLogger(__name__)


class EventQueue:
    """Bounded stable priority heap. Higher-priority events may evict background work."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._heap = []
        self._sequence = itertools.count()
        self._ready = asyncio.Event()

    def put(self, event: Event) -> bool:
        item = (event.priority, next(self._sequence), event)
        if len(self._heap) >= self.capacity:
            worst = max(self._heap, key=lambda entry: entry[:2])
            if item[0] >= worst[0]:
                return False
            self._heap.remove(worst)
            heapq.heapify(self._heap)
        heapq.heappush(self._heap, item)
        self._ready.set()
        return True

    async def get(self) -> Event:
        while not self._heap:
            self._ready.clear()
            await self._ready.wait()
        return heapq.heappop(self._heap)[2]


class AutonomyEngine:
    def __init__(
        self,
        robot: RobotAdapter,
        provider: DecisionProvider,
        settings: Settings,
        *,
        clock=time.time,
        personality: tuple[str, ...] = (),
    ):
        self.robot = robot
        self.provider = provider
        self.settings = settings
        self.clock = clock
        self.personality = personality
        self.events = EventQueue(settings.queue_size)
        self.memory = Memory(settings.history_size, settings.memory_path)
        self.perception = Perception()
        self.actions = ActionExecutor(robot, settings)
        self.actions.on_control_lost = self._control_lost
        self.transitions: deque[State] = deque(maxlen=settings.history_size)
        self.state = State.BOOT
        self.transitions.append(self.state)
        self.stopped = False
        self._cycle_lock = asyncio.Lock()
        self._active: asyncio.Task | None = None
        self._runner: asyncio.Task | None = None
        self._scheduler: asyncio.Task | None = None
        self._person_present = False
        self._analysis_succeeded = False
        self._last_analysis_at: float | None = None

    def _transition(self, state: State) -> None:
        self.state = state
        self.transitions.append(state)

    def _control_lost(self) -> None:
        self.stop()
        self._transition(State.ERROR)

    def submit(self, event: Event) -> bool:
        if event.kind == EventKind.USER_STOP:
            self.stop()
            return True
        if event.kind == EventKind.DEVICE_DISCONNECTED:
            self.stop()
            self._transition(State.ERROR)
            return True
        return False if self.stopped else self.events.put(event)

    def stop(self) -> None:
        self.stopped = True
        self.actions.stop()  # synchronous latch before any cancellation await
        self._transition(State.ERROR if self.state == State.ERROR else State.STOPPED)
        current = asyncio.current_task()
        for task in (self._active, self._scheduler, self._runner):
            if task is not None and task is not current:
                task.cancel()

    async def aclose(self) -> None:
        self.stop()
        current = asyncio.current_task()
        tasks = {
            t
            for t in (self._active, self._scheduler, self._runner)
            if t is not None and t is not current
        }
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.actions.aclose()
        self.memory.close()

    async def _schedule(self) -> None:
        while not self.stopped:
            self.submit(Event(kind=EventKind.TIMER_OBSERVE))
            await asyncio.sleep(self.settings.observe_interval_s)

    async def run(self) -> None:
        if self._runner is not None:
            raise RuntimeError("engine already has a runner")
        if self.stopped:
            return
        self._runner = asyncio.current_task()
        self._transition(State.IDLE)
        self._scheduler = asyncio.create_task(self._schedule(), name="stackchan-observer")
        try:
            while not self.stopped:
                event = await self.events.get()
                await self.step(event)
        except asyncio.CancelledError:
            if not self.stopped:
                raise
        finally:
            self.stop()

    async def step(self, event: Event) -> ActionResult:
        if event.priority == 0:
            if event.kind != EventKind.CLOUD_API_ERROR:
                self.submit(event)
            return ActionResult(code="stopped" if self.stopped else "cloud_error")
        async with self._cycle_lock:
            if self.stopped:
                return ActionResult(code="stopped")
            if self.actions.faulted:
                self.stopped = True
                self._transition(State.ERROR)
                return ActionResult(code="device_fault")
            self._active = asyncio.current_task()
            if self.state == State.BOOT:
                self._transition(State.IDLE)
            try:
                async with asyncio.timeout(self.settings.operation_timeout_s):
                    self._transition(State.OBSERVE)
                    status = await self.robot.status()
                    if not status.connected:
                        raise ConnectionError("disconnected")
                    observation = self.perception.process(await self.robot.capture())
                    if (
                        observation.person_present
                        and not self._person_present
                        and event.priority >= 2
                    ):
                        event = Event(kind=EventKind.PERSON_DETECTED)
                    self._person_present = observation.person_present is True
                    if (
                        event.kind == EventKind.TIMER_OBSERVE
                        and not observation.scene_changed
                        and self._analysis_succeeded
                        and self._last_analysis_at is not None
                        and self.clock() - self._last_analysis_at
                        < self.settings.max_unchanged_interval_s
                    ):
                        return ActionResult(code="unchanged")
                    self._transition(State.THINK)
                    decision = await self.provider.decide(
                        observation,
                        DecisionContext(
                            event=event,
                            status=status,
                            recent=self.memory.recent(),
                            personality=self.personality,
                            max_step_deg=self.settings.max_step_deg,
                        ),
                    )
                    self._analysis_succeeded = getattr(self.provider, "last_succeeded", True)
                    self._last_analysis_at = self.clock()
                    # Drop local reference before action dispatch; no media goes into memory.
                    del observation
                    self._transition(State.VALIDATE)
                    decision = Decision.model_validate(decision.model_dump())
                    now = self.clock()
                    last_spoken = self.memory.last_spoken_at
                    if (
                        decision.intent == "speak"
                        and last_spoken is not None
                        and event.kind != EventKind.VOICE_REQUEST
                        and now - last_spoken < self.settings.speech_cooldown_s
                    ):
                        result = ActionResult(code="speech_cooldown")
                    else:
                        self._transition(State.ACT)
                        result = await self.actions.execute(
                            decision, explicit_request=event.kind == EventKind.VOICE_REQUEST
                        )
                    self.memory.record(now, event.kind, decision.intent, result.code)
                    if result.code == "device_fault" or self.actions.faulted:
                        self.stopped = True
                        self.actions.stop()
                        self._transition(State.ERROR)
                        return result
                self._transition(State.COOLDOWN)
                await asyncio.sleep(self.settings.cooldown_s)
                return result
            except asyncio.CancelledError:
                if self.stopped:
                    return ActionResult(code="stopped")
                raise
            except ConnectionError:
                self.stopped = True
                self.actions.stop()
                self._transition(State.ERROR)
                return ActionResult(code="device_fault")
            except Exception:
                self._analysis_succeeded = False
                if self.actions.faulted:
                    self.stopped = True
                    self.actions.stop()
                    self._transition(State.ERROR)
                # Narrow external exception details to one fixed, non-private event code.
                logger.warning("autonomy_cycle_unavailable")
                return ActionResult(code="cycle_unavailable")
            finally:
                self._active = None
                if not self.stopped:
                    self._transition(State.IDLE)
