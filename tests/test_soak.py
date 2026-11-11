import asyncio
import json
import os
import subprocess
import sys
import time

import pytest


async def test_soak_measures_bounds_restarts_and_virtual_time():
    from stackchan_autonomy.soak import SoakConfig, run_soak

    baseline = len(asyncio.all_tasks())
    report = await run_soak(
        SoakConfig(
            cycles=40,
            warmup_cycles=5,
            restart_every=10,
            sample_every=5,
            history_limit=8,
            virtual_step_s=30,
        )
    )
    assert report.passed, report.violations
    assert report.failure is None
    assert report.cycles == 40 and report.measured_cycles == 35
    assert report.virtual_elapsed_s == 1200
    assert report.wall_elapsed_s < 1200
    assert report.restarts == report.restoration_checks == 3
    assert max(report.history_peak, report.transition_peak, report.robot_history_peak) <= 8
    assert report.remaining_tasks == 0
    assert report.cloud_requests == 0
    assert len(asyncio.all_tasks()) <= baseline


async def test_soak_records_disconnection_result_before_cleanup(monkeypatch):
    from stackchan_autonomy import soak

    original = soak.FakeRobotAdapter

    class DisconnectingRobot(original):
        captures = 0

        async def capture(self):
            self.captures += 1
            if self.captures == 7:
                raise ConnectionError("private-device-error-detail")
            return await super().capture()

    monkeypatch.setattr(soak, "FakeRobotAdapter", DisconnectingRobot)
    report = await soak.run_soak(soak.SoakConfig(cycles=20, warmup_cycles=2))
    assert not report.passed and report.violations == ("engine_failure",)
    assert report.cycles == 7 and sum(report.results.values()) == 6
    assert report.failure.model_dump(mode="json") == {
        "cycle": 7,
        "event": "TOUCH_TAP",
        "result_code": "device_fault",
        "engine_state": "ERROR",
        "engine_stopped": True,
        "action_stopped": True,
        "action_faulted": False,
        "lease_lost": False,
    }
    assert report.remaining_tasks == 0
    assert "private-device-error-detail" not in report.model_dump_json()


async def test_soak_classifies_real_expired_lease_without_retry(monkeypatch):
    from stackchan_autonomy import soak

    lease_now = [1000.0]
    original_engine = soak.AutonomyEngine
    original_decide = soak.MockDecisionProvider.decide
    decisions = 0

    def engine_with_control_clock(*args, **kwargs):
        engine = original_engine(*args, **kwargs)
        engine.actions.lease.clock = lambda: lease_now[0]
        return engine

    async def expire_before_third_decision(self, observation, context):
        nonlocal decisions
        decisions += 1
        if decisions == 3:
            lease_now[0] += 20  # Real SQLite ownership expires; no real sleep is required.
        return await original_decide(self, observation, context)

    monkeypatch.setattr(soak, "AutonomyEngine", engine_with_control_clock)
    monkeypatch.setattr(soak.MockDecisionProvider, "decide", expire_before_third_decision)
    report = await soak.run_soak(soak.SoakConfig(cycles=20, warmup_cycles=1))
    assert not report.passed and report.violations == ("engine_failure",)
    assert report.cycles == decisions == 3
    assert report.failure.result_code == "device_fault"
    assert report.failure.event.value == "VOICE_REQUEST"
    assert report.failure.engine_state.value == "ERROR"
    assert report.failure.lease_lost and report.failure.action_faulted
    assert report.failure.engine_stopped and report.failure.action_stopped
    assert report.remaining_tasks == 0 and report.cloud_requests == 0


async def test_soak_distinguishes_sqlite_lock_failure_from_control_loss(monkeypatch):
    import sqlite3

    from stackchan_autonomy import soak
    from stackchan_autonomy.control import ControlLease

    original_check = ControlLease.check
    original_decide = soak.MockDecisionProvider.decide
    decisions = 0
    lock_next_check = False

    async def arrange_lock(self, observation, context):
        nonlocal decisions, lock_next_check
        decisions += 1
        if decisions == 3:
            lock_next_check = True
        return await original_decide(self, observation, context)

    def check_with_competing_writer(self, handle):
        nonlocal lock_next_check
        if not lock_next_check:
            return original_check(self, handle)
        lock_next_check = False
        db = sqlite3.connect(self.store.path, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            return original_check(self, handle)
        finally:
            db.rollback()
            db.close()

    monkeypatch.setattr(ControlLease, "check", check_with_competing_writer)
    monkeypatch.setattr(soak.MockDecisionProvider, "decide", arrange_lock)
    report = await soak.run_soak(soak.SoakConfig(cycles=20, warmup_cycles=1))
    assert not report.passed and report.violations == ("engine_failure",)
    assert report.cycles == 3
    assert report.failure.result_code == "cycle_unavailable"
    assert report.failure.engine_state.value == "IDLE"
    assert not report.failure.lease_lost and not report.failure.action_faulted
    assert not report.failure.engine_stopped  # Capture precedes diagnostic cleanup's stop.
    assert report.remaining_tasks == 0


async def test_soak_redacts_unrecognized_result_strings(monkeypatch):
    from stackchan_autonomy import soak
    from stackchan_autonomy.models import ActionResult

    original_step = soak.AutonomyEngine.step

    async def unexpected_engine_result(self, event):
        await original_step(self, event)
        return ActionResult(code="private-result-never-export")

    monkeypatch.setattr(soak.AutonomyEngine, "step", unexpected_engine_result)
    report = await soak.run_soak(soak.SoakConfig(cycles=20, warmup_cycles=1))
    assert not report.passed and "engine_failure" in report.violations
    assert report.failure.result_code == "unrecognized_result"
    assert "private-result-never-export" not in report.model_dump_json()


async def test_soak_observes_cycle_delays_and_wall_clock_adjustment(monkeypatch):
    from types import SimpleNamespace

    from stackchan_autonomy import soak

    wall_offset = [0.0]
    original_decide = soak.MockDecisionProvider.decide
    decisions = 0

    async def adjust_clock(self, observation, context):
        nonlocal decisions
        decisions += 1
        if decisions == 3:
            wall_offset[0] = 20.0
        await asyncio.sleep(0.01)
        return await original_decide(self, observation, context)

    # Replace only the runner's clock namespace; the event loop and real lease keep
    # their actual clocks. This observes clock drift without faking scheduler progress.
    monkeypatch.setattr(
        soak,
        "time",
        SimpleNamespace(monotonic=time.monotonic, time=lambda: time.time() + wall_offset[0]),
    )
    monkeypatch.setattr(soak.MockDecisionProvider, "decide", adjust_clock)
    report = await soak.run_soak(soak.SoakConfig(cycles=8, warmup_cycles=2, interval_s=0.01))
    assert report.passed, report.violations
    assert report.max_cycle_duration_s >= 0.01
    assert report.max_cycle_gap_s >= 0.01
    assert report.max_wall_clock_drift_s >= 19
    assert report.failure is None


async def test_soak_ignores_application_environment_and_never_touches_user_db(
    monkeypatch, tmp_path
):
    from stackchan_autonomy.soak import SoakConfig, run_soak

    path = tmp_path / "operator.sqlite3"
    path.write_bytes(b"operator-data-preserve")
    for key, value in {
        "STACKCHAN_STATE_PATH": str(path),
        "STACKCHAN_MEMORY_PATH": str(path),
        "STACKCHAN_CLOUD_ENABLED": "true",
        "STACKCHAN_HARDWARE_ENABLED": "true",
        "STACKCHAN_HISTORY_SIZE": "not-a-number",
        "OPENAI_API_KEY": "private-secret",
    }.items():
        monkeypatch.setenv(key, value)
    report = await run_soak(SoakConfig(cycles=12, warmup_cycles=3, restart_every=5))
    assert report.passed and report.cloud_requests == 0
    assert path.read_bytes() == b"operator-data-preserve"
    assert "private-secret" not in report.model_dump_json()


@pytest.mark.parametrize("provider_delay", [0, 0.25])
async def test_soak_duration_is_real_monotonic_time(monkeypatch, provider_delay):
    from stackchan_autonomy.soak import MockDecisionProvider, SoakConfig, run_soak

    original = MockDecisionProvider.decide

    async def delayed(self, observation, context):
        await asyncio.sleep(provider_delay)
        return await original(self, observation, context)

    monkeypatch.setattr(MockDecisionProvider, "decide", delayed)

    started = time.monotonic()
    report = await run_soak(
        SoakConfig(
            cycles=None,
            duration_s=0.4,
            interval_s=0.01,
            warmup_cycles=2,
            restart_every=5,
        )
    )
    elapsed = time.monotonic() - started
    assert elapsed >= report.wall_elapsed_s >= 0.4
    assert report.virtual_elapsed_s is None
    if report.measured_cycles:
        assert report.passed, report.violations
    else:
        assert not report.passed
        assert report.violations == ("insufficient_measurement",)


async def test_soak_short_run_cannot_claim_a_measurement_pass():
    from stackchan_autonomy.soak import SoakConfig, run_soak

    report = await run_soak(
        SoakConfig(
            cycles=None,
            duration_s=0.01,
            interval_s=0.01,
            warmup_cycles=100,
        )
    )
    assert not report.passed
    assert "insufficient_measurement" in report.violations
    assert report.python_traced_growth_bytes is None


async def test_soak_detects_retained_python_growth(monkeypatch):
    from stackchan_autonomy import soak

    retained = []
    original = soak.MockDecisionProvider.decide

    async def leaking(self, observation, context):
        retained.append(bytearray(50_000))
        return await original(self, observation, context)

    monkeypatch.setattr(soak.MockDecisionProvider, "decide", leaking)
    report = await soak.run_soak(
        soak.SoakConfig(
            cycles=25,
            warmup_cycles=5,
            max_heap_growth_bytes=1024,
        )
    )
    assert not report.passed
    assert "python_heap_growth" in report.violations
    assert report.python_traced_growth_bytes > 1024


async def test_soak_reports_pending_tasks_without_claiming_success(monkeypatch):
    from stackchan_autonomy import soak

    leaked = []
    original = soak.MockDecisionProvider.decide

    async def leaking(self, observation, context):
        leaked.append(asyncio.create_task(asyncio.Event().wait()))
        return await original(self, observation, context)

    monkeypatch.setattr(soak.MockDecisionProvider, "decide", leaking)
    try:
        report = await soak.run_soak(soak.SoakConfig(cycles=12, warmup_cycles=3))
        assert not report.passed
        assert report.remaining_tasks > 0
        assert "tasks_remaining" in report.violations
    finally:
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)


async def test_soak_cancellation_closes_engine_before_removing_temporary_db(monkeypatch, tmp_path):
    from pathlib import Path

    from stackchan_autonomy import soak

    created = []
    original = soak.tempfile.TemporaryDirectory

    def temporary(**kwargs):
        directory = original(dir=tmp_path, **kwargs)
        created.append(Path(directory.name))
        return directory

    monkeypatch.setattr(soak.tempfile, "TemporaryDirectory", temporary)
    task = asyncio.create_task(
        soak.run_soak(
            soak.SoakConfig(
                cycles=None,
                duration_s=5,
                interval_s=0.01,
                warmup_cycles=2,
            )
        )
    )
    try:
        async with asyncio.timeout(3):
            while not created or not (created[0] / "control.sqlite3").exists():
                await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not created[0].exists()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "values",
    [
        {"cycles": 5, "warmup_cycles": 5},
        {"cycles": None, "duration_s": None},
        {"duration_s": 1},
        {"interval_s": -1},
        {"virtual_step_s": float("nan")},
    ],
)
def test_soak_rejects_unmeasurable_or_invalid_configuration(values):
    from stackchan_autonomy.soak import SoakConfig

    with pytest.raises(ValueError):
        SoakConfig(**values)


def test_soak_cli_writes_only_metadata_and_preserves_failure_exit(tmp_path):
    report_path = tmp_path / "report folder" / "summary.json"
    env = dict(os.environ) | {"OPENAI_API_KEY": "private-report-secret"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "stackchan_autonomy.soak",
            "--cycles",
            "20",
            "--warmup-cycles",
            "5",
            "--restart-every",
            "10",
            "--virtual-step-s",
            "30",
            "--report",
            str(report_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == report
    assert report["passed"] and report["virtual_elapsed_s"] == 600
    assert "private-report-secret" not in result.stdout
    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "stackchan_autonomy.soak",
            "--duration-s",
            "0.01",
            "--interval-s",
            "0.01",
            "--warmup-cycles",
            "100",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert failed.returncode == 1, failed.stderr
    assert not json.loads(failed.stdout)["passed"]
