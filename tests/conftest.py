import asyncio
import json

import pytest


@pytest.fixture(autouse=True)
def isolated_coordination_state(monkeypatch, tmp_path):
    # Real CLI subprocesses inherit this path; no test spends another test's quota.
    monkeypatch.setenv("STACKCHAN_STATE_PATH", str(tmp_path / "autonomy.sqlite3"))


@pytest.fixture
async def lease_timing_probe():
    """Opt-in timings only: no timeout, lease, operation or outcome changes."""
    from stackchan_autonomy.timing_diagnostics import TimingProbe

    probe = TimingProbe()
    probe.start_loop_monitor(asyncio.get_running_loop())
    try:
        yield probe
    finally:
        probe.stop_loop_monitor()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    probe = item.funcargs.get("lease_timing_probe")
    if probe is None:
        yield
        return
    # Collect in the runner's context: older pytest-asyncio releases do not
    # propagate contextvars from a separate async-fixture setup task to tests.
    with probe.collect():
        yield


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    probe = item.funcargs.get("lease_timing_probe")
    if report.when == "call" and report.failed and probe is not None:
        # Snapshot schema has only bounded stage/operation labels and durations;
        # never emit arguments, paths, SQL, credentials or exception text here.
        print("LEASE_TIMING_DIAGNOSTICS " + json.dumps({"timing_diagnostics": probe.snapshot()}))
