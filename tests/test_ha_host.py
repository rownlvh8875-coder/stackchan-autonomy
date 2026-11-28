"""Exercise the managed host launcher with disposable credentials and SQLite files."""

import concurrent.futures
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stackchan_autonomy.budget import SQLiteRequestBudget
from stackchan_autonomy.settings import Settings
from stackchan_autonomy.state_store import StateUnavailable

PRIVATE = "synthetic-host-key-do-not-print"
RUN_WORKER = """
import asyncio
import sys
from stackchan_autonomy import ha_host, ha_voice
from stackchan_autonomy.budget import SQLiteRequestBudget

async def serve(settings, port=10300):
    assert settings.budget_require_existing and port == 10300
    assert settings.api_key.get_secret_value() == "synthetic-host-key-do-not-print"
    budget = SQLiteRequestBudget(settings)
    for _ in range(6):
        if not budget.reserve(100):
            print("BLOCKED", flush=True)
            return
    print("COMMITTED", flush=True)
    await asyncio.Event().wait()

role = sys.argv[1]
if role == "voice":
    ha_voice.serve = serve
else:
    from stackchan_autonomy import ha_conversation
    ha_conversation.serve = serve
raise SystemExit(ha_host.main([role]))
"""


@pytest.fixture
def host_env(tmp_path):
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "openai-key").write_bytes(PRIVATE.encode() + b"\n")
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA"}
    } | {
        "CREDENTIALS_DIRECTORY": str(credentials),
        "STACKCHAN_STATE_PATH": str(tmp_path / "budget.sqlite3"),
        "STACKCHAN_BUDGET_NAMESPACE": "test:managed",
        "STACKCHAN_CLOUD_ENABLED": "true",
        "STACKCHAN_AUDIO_TRANSMISSION": "true",
        "STACKCHAN_OPENAI_MODEL": "offline-model",
        "STACKCHAN_REQUESTS_PER_MINUTE": "6",
    }


def host_cli(env, *args):
    return subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy.ha_host", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_managed_worker_restart_recovers_committed_budget_after_kill(host_env):
    init = host_cli(host_env, "initialize-budget")
    assert init.returncode == 0 and init.stdout.strip() == "HA_HOST_BUDGET_INITIALIZED"
    worker = subprocess.Popen(
        [sys.executable, "-c", RUN_WORKER, "voice"],
        env=host_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Pipe transfer to a helper avoids an unbounded readline if boot fails.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                report = pool.submit(worker.stdout.readline).result(timeout=15)
                assert report.strip() == "COMMITTED"
            finally:
                worker.kill()
    finally:
        worker.communicate(timeout=10)

    restarted = subprocess.run(
        [sys.executable, "-c", RUN_WORKER, "conversation"],
        env=host_env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert restarted.returncode == 0 and restarted.stdout.strip() == "BLOCKED"
    assert PRIVATE not in restarted.stdout + restarted.stderr
    repeated_init = host_cli(host_env, "initialize-budget")
    assert repeated_init.returncode == 2
    assert repeated_init.stderr.strip() == "HA_HOST_BUDGET_UNAVAILABLE"


def test_offline_check_requires_credential_and_reports_only_status(host_env):
    assert host_cli(host_env, "initialize-budget").returncode == 0
    result = host_cli(host_env, "check")
    assert result.returncode == 0 and result.stdout.strip() == "HA_HOST_READY"
    assert PRIVATE not in result.stdout + result.stderr
    (Path(host_env["CREDENTIALS_DIRECTORY"]) / "openai-key").unlink()
    result = host_cli(host_env, "check")
    assert result.returncode == 2 and result.stderr.strip() == "HA_HOST_CONFIG_REQUIRED"


@pytest.mark.parametrize("failure", ["missing", "blank", "wrong_namespace"])
def test_managed_boot_does_not_make_a_new_budget(host_env, failure):
    path = Path(host_env["STACKCHAN_STATE_PATH"])
    if failure == "blank":
        path.touch()
    if failure == "wrong_namespace":
        assert host_cli(host_env, "initialize-budget").returncode == 0
        host_env["STACKCHAN_BUDGET_NAMESPACE"] = "test:replacement"
    result = host_cli(host_env, "voice")
    assert result.returncode == 2
    assert result.stderr.strip() == "HA_HOST_BUDGET_UNAVAILABLE"
    if failure == "missing":
        assert not path.exists()
    elif failure == "blank":
        assert path.stat().st_size == 0


def test_running_worker_will_not_recreate_missing_budget(tmp_path, monkeypatch):
    path = tmp_path / "managed.sqlite3"
    monkeypatch.setenv("STACKCHAN_STATE_PATH", str(path))
    config = Settings(_env_file=None, budget_namespace="test:managed")
    SQLiteRequestBudget(config).record_usage()
    protected = SQLiteRequestBudget(config.model_copy(update={"budget_require_existing": True}))
    assert protected.reserve(100)
    path.unlink()
    with pytest.raises(StateUnavailable):
        protected.reserve(101)
    assert not path.exists()


def test_disabled_cloud_blocks_workers_even_with_budget_and_credential(host_env):
    assert host_cli(host_env, "initialize-budget").returncode == 0
    host_env["STACKCHAN_CLOUD_ENABLED"] = "false"
    result = host_cli(host_env, "voice")
    assert result.returncode == 2 and result.stderr.strip() == "HA_HOST_CONFIG_REQUIRED"
    assert PRIVATE not in result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="requires Linux systemd tools")
def test_systemd_verifies_both_instances_and_startup_target(tmp_path):
    source = Path(__file__).resolve().parents[1] / "config" / "home_assistant" / "systemd"
    template = (source / "stackchan-assist@.service").read_text()
    services = []
    for role in ("voice", "conversation"):
        # Only substitute the installed interpreter path on the test machine.
        service = template.replace("/opt/stackchan/venv-%i/bin/python", "/usr/bin/python3")
        instance = tmp_path / f"stackchan-assist@{role}.service"
        instance.write_text(service.replace("%i", role))
        services.append(str(instance))
    target = tmp_path / "stackchan-assist.target"
    shutil.copy(source / target.name, target)
    result = subprocess.run(
        ["systemd-analyze", "--man=no", "--recursive-errors=no", "verify", str(target), *services],
        env={**os.environ, "SYSTEMD_UNIT_PATH": str(tmp_path) + ":"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
