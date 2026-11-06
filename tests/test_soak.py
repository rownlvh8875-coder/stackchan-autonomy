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
    assert report.cycles == 40 and report.measured_cycles == 35
    assert report.virtual_elapsed_s == 1200
    assert report.wall_elapsed_s < 1200
    assert report.restarts == report.restoration_checks == 3
    assert max(report.history_peak, report.transition_peak, report.robot_history_peak) <= 8
    assert report.remaining_tasks == 0
    assert report.cloud_requests == 0
    assert len(asyncio.all_tasks()) <= baseline


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
