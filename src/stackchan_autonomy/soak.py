"""Bounded, offline-only stability diagnostic; real and virtual clocks are distinct."""

import argparse
import asyncio
import gc
import os
import tempfile
import time
import tracemalloc
from collections import Counter
from contextlib import AsyncExitStack
from pathlib import Path

from pydantic import Field, model_validator

from .decision import MockDecisionProvider
from .engine import AutonomyEngine
from .models import Event, EventKind, State, StrictModel
from .robot import FakeRobotAdapter
from .settings import Settings


class SoakConfig(StrictModel):
    cycles: int | None = Field(default=1000, ge=1, le=10_000_000)
    duration_s: float | None = Field(default=None, gt=0, le=86400)
    interval_s: float = Field(default=0, ge=0, le=60)
    virtual_step_s: float | None = Field(default=None, gt=0, le=3600)
    warmup_cycles: int = Field(default=100, ge=1, le=10000)
    restart_every: int = Field(default=250, ge=1, le=10_000_000)
    sample_every: int = Field(default=100, ge=1, le=100000)
    history_limit: int = Field(default=100, ge=2, le=1000)
    max_heap_growth_bytes: int = Field(default=2_000_000, ge=0)
    max_task_growth: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def measurable(self):
        if (self.cycles is None) == (self.duration_s is None):
            raise ValueError("choose exactly one cycle or real duration bound")
        if self.cycles is not None and self.cycles <= self.warmup_cycles:
            raise ValueError("cycles must exceed warmup")
        return self


class SoakFailure(StrictModel):
    cycle: int
    event: EventKind
    result_code: str
    engine_state: State
    engine_stopped: bool
    action_stopped: bool
    action_faulted: bool
    lease_lost: bool


class SoakReport(StrictModel):
    passed: bool
    cycles: int
    measured_cycles: int
    wall_elapsed_s: float
    virtual_elapsed_s: float | None
    requested_duration_s: float | None
    python_traced_growth_bytes: int | None
    python_traced_peak_bytes: int
    max_live_tasks: int
    task_growth: int
    remaining_tasks: int
    history_peak: int
    transition_peak: int
    robot_history_peak: int
    restarts: int
    restoration_checks: int
    cloud_requests: int = 0
    results: dict[str, int]
    violations: tuple[str, ...]
    failure: SoakFailure | None = None
    max_cycle_duration_s: float | None = Field(default=None, ge=0)
    max_cycle_gap_s: float | None = Field(default=None, ge=0)
    max_wall_clock_drift_s: float | None = Field(default=None, ge=0)


_ALLOWED_RESULTS = frozenset(
    {
        "executed",
        "idle",
        "speech_cooldown",
        "duplicate",
        "unchanged",
        "automatic_speech_disabled",
        "command_rate_limit",
    }
)
_REPORTED_RESULTS = _ALLOWED_RESULTS | {
    "device_fault",
    "lease_busy",
    "stopped",
    "cloud_error",
    "memory_unavailable",
    "cycle_unavailable",
    "queue_full",
    "unsafe",
    "hardware_disabled",
}


class _IsolatedSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (init_settings,)  # Never read an operator's .env, API key or DB path.


async def run_soak(config: SoakConfig) -> SoakReport:
    """Standalone diagnostic. CLI's asyncio.run also closes unexpected leftover tasks."""
    initial_tasks = asyncio.all_tasks()
    owns_tracer = not tracemalloc.is_tracing()
    if owns_tracer:
        tracemalloc.start()
    cycles = restarts = restoration_checks = 0
    baseline_heap = baseline_tasks = None
    growth = None
    max_tasks = task_growth = history_peak = transition_peak = robot_peak = 0
    results = Counter()
    violations = set()
    failure = None
    max_cycle_duration = max_cycle_gap = max_clock_drift = 0.0
    virtual_start = 1_700_000_000.0
    started = time.monotonic()
    previous_finished = started
    previous_wall = time.time()
    engine = None
    try:
        async with AsyncExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="stackchan soak "))

            async def close_engine():
                nonlocal engine
                current, engine = engine, None
                if current is not None:
                    await current.aclose()

            stack.push_async_callback(close_engine)  # Runs before the temporary DB is removed.
            root = Path(directory)
            settings = _IsolatedSettings(
                _env_file=None,
                state_path=root / "control.sqlite3",
                memory_path=root / "memory.sqlite3",
                control_resource="soak:isolated",
                history_size=config.history_limit,
                cooldown_s=0,
                command_interval_s=0,
                cloud_enabled=False,
                hardware_enabled=False,
                image_transmission=False,
                audio_transmission=False,
                dry_run=True,
            )

            def clock():
                return (
                    virtual_start + cycles * config.virtual_step_s
                    if config.virtual_step_s is not None
                    else time.time()
                )

            def create_engine():
                return AutonomyEngine(
                    FakeRobotAdapter(history_size=config.history_limit),
                    MockDecisionProvider(),
                    settings,
                    clock=clock,
                )

            engine = create_engine()
            engine.memory.update_preferences(minimum_speech_interval_s=600)
            kinds = (
                EventKind.TIMER_OBSERVE,
                EventKind.TOUCH_TAP,
                EventKind.VOICE_REQUEST,
                EventKind.PERSON_DETECTED,
                EventKind.SCENE_CHANGED,
            )
            while True:
                if config.cycles is not None and cycles >= config.cycles:
                    break
                if (
                    config.duration_s is not None
                    and time.monotonic() - started >= config.duration_s
                ):
                    break
                if cycles and cycles % config.restart_every == 0:
                    before = engine.memory.snapshot()
                    await engine.aclose()
                    engine = create_engine()
                    if engine.memory.snapshot() != before:
                        violations.add("restart_metadata_mismatch")
                    restarts += 1
                    restoration_checks += 1
                engine.robot.person_present = cycles % 20 >= 10
                event_kind = kinds[cycles % len(kinds)]
                cycle_started = time.monotonic()
                wall_started = time.time()
                gap = cycle_started - previous_finished
                max_cycle_gap = max(max_cycle_gap, gap)
                max_clock_drift = max(max_clock_drift, abs(wall_started - previous_wall - gap))
                result = await engine.step(Event(kind=event_kind))
                cycle_finished = time.monotonic()
                wall_finished = time.time()
                duration = cycle_finished - cycle_started
                max_cycle_duration = max(max_cycle_duration, duration)
                max_clock_drift = max(max_clock_drift, abs(wall_finished - wall_started - duration))
                previous_finished, previous_wall = cycle_finished, wall_finished
                cycles += 1
                if result.code not in _ALLOWED_RESULTS or engine.stopped:
                    violations.add("engine_failure")
                    failure = SoakFailure(
                        cycle=cycles,
                        event=event_kind,
                        result_code=(
                            result.code
                            if result.code in _REPORTED_RESULTS
                            else "unrecognized_result"
                        ),
                        engine_state=engine.state,
                        engine_stopped=engine.stopped,
                        action_stopped=engine.actions.stopped,
                        action_faulted=engine.actions.faulted,
                        lease_lost=engine.actions.lease_lost,
                    )
                    break
                results[result.code] += 1
                history_peak = max(history_peak, len(engine.memory.recent()))
                transition_peak = max(transition_peak, len(engine.transitions))
                robot_peak = max(robot_peak, len(engine.robot.history))
                live_tasks = len(asyncio.all_tasks() - initial_tasks)
                max_tasks = max(max_tasks, live_tasks)
                if cycles == config.warmup_cycles:
                    gc.collect()
                    baseline_heap = tracemalloc.get_traced_memory()[0]
                    baseline_tasks = live_tasks
                if baseline_tasks is not None:
                    task_growth = max(task_growth, live_tasks - baseline_tasks)
                if baseline_heap is not None and cycles % config.sample_every == 0:
                    gc.collect()
                    growth = tracemalloc.get_traced_memory()[0] - baseline_heap
                    if growth > config.max_heap_growth_bytes:
                        violations.add("python_heap_growth")
                    if task_growth > config.max_task_growth:
                        violations.add("task_growth")
                if violations:
                    break
                pause = config.interval_s
                if config.duration_s is not None:
                    pause = min(pause, max(0, config.duration_s - (time.monotonic() - started)))
                await asyncio.sleep(pause)
            if baseline_heap is not None:
                gc.collect()
                growth = tracemalloc.get_traced_memory()[0] - baseline_heap
                if growth > config.max_heap_growth_bytes:
                    violations.add("python_heap_growth")
            if baseline_tasks is not None and task_growth > config.max_task_growth:
                violations.add("task_growth")
            if max(history_peak, transition_peak, robot_peak) > config.history_limit:
                violations.add("history_bound")
            if cycles <= config.warmup_cycles:
                violations.add("insufficient_measurement")
            await engine.aclose()
            engine = None
        await asyncio.sleep(0)
        remaining = len(asyncio.all_tasks() - initial_tasks)
        if remaining:
            violations.add("tasks_remaining")
        return SoakReport(
            passed=not violations,
            cycles=cycles,
            measured_cycles=max(0, cycles - config.warmup_cycles),
            wall_elapsed_s=time.monotonic() - started,
            virtual_elapsed_s=cycles * config.virtual_step_s
            if config.virtual_step_s is not None
            else None,
            requested_duration_s=config.duration_s,
            python_traced_growth_bytes=growth,
            python_traced_peak_bytes=tracemalloc.get_traced_memory()[1],
            max_live_tasks=max_tasks,
            task_growth=task_growth,
            remaining_tasks=remaining,
            history_peak=history_peak,
            transition_peak=transition_peak,
            robot_history_peak=robot_peak,
            restarts=restarts,
            restoration_checks=restoration_checks,
            results=dict(results),
            violations=tuple(sorted(violations)),
            failure=failure,
            max_cycle_duration_s=max_cycle_duration,
            max_cycle_gap_s=max_cycle_gap,
            max_wall_clock_drift_s=max_clock_drift,
        )
    finally:
        if owns_tracer:
            tracemalloc.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    bounds = parser.add_mutually_exclusive_group()
    bounds.add_argument("--cycles", help="bounded cycle count (default1000)")
    bounds.add_argument("--duration-s", help="real monotonic run duration, up to86400 seconds")
    parser.add_argument("--interval-s", default="0", help="real pacing interval, default0")
    parser.add_argument("--virtual-step-s", help="explicit virtual seconds per cycle")
    parser.add_argument("--warmup-cycles", default="100")
    parser.add_argument("--restart-every", default="250")
    parser.add_argument("--report", type=Path, help="optional metadata-only JSON report path")
    args = parser.parse_args(argv)
    try:
        config = SoakConfig(
            cycles=None if args.duration_s is not None else int(args.cycles or "1000"),
            duration_s=float(args.duration_s) if args.duration_s is not None else None,
            interval_s=float(args.interval_s),
            virtual_step_s=float(args.virtual_step_s) if args.virtual_step_s is not None else None,
            warmup_cycles=int(args.warmup_cycles),
            restart_every=int(args.restart_every),
        )
        report = asyncio.run(run_soak(config))
        payload = report.model_dump_json()
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.report.with_name(f"{args.report.name}.{os.getpid()}.tmp")
            try:
                temporary.write_text(payload + "\n", encoding="utf-8")
                temporary.replace(args.report)
            finally:
                temporary.unlink(missing_ok=True)
        print(payload)
        return 0 if report.passed else 1
    except KeyboardInterrupt:
        return 130
    except (ValueError, TypeError):
        parser.exit(2, "Invalid soak settings; see SOAK.md.\n")
    except OSError:
        parser.exit(2, "Soak storage/report unavailable.\n")


if __name__ == "__main__":
    raise SystemExit(main())
