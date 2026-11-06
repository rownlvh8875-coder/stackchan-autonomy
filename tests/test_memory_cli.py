import json
import os
import subprocess
import sys


def run_cli(tmp_path, *args, enabled=True):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("STACKCHAN_MEMORY_")
    }
    env["PYTHONUTF8"] = "1"
    if enabled:
        env["STACKCHAN_MEMORY_PATH"] = str(tmp_path / "folder with spaces" / "memory.sqlite3")
    return subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy.memory_cli", *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )


def test_cli_set_show_and_clear_persist_across_processes(tmp_path):
    result = run_cli(
        tmp_path, "set", "--automatic-speech", "off", "--minimum-speech-interval", "600"
    )
    assert result.returncode == 0, result.stderr
    result = run_cli(tmp_path, "show")
    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout)
    assert snapshot["preferences"] == {
        "automatic_speech_enabled": False,
        "minimum_speech_interval_s": 600,
    }
    assert snapshot["recent"] == []
    assert run_cli(tmp_path, "clear").returncode == 0
    assert (
        json.loads(run_cli(tmp_path, "show").stdout)["preferences"]["automatic_speech_enabled"]
        is True
    )


def test_cli_requires_explicit_memory_opt_in(tmp_path):
    result = run_cli(tmp_path, "show", enabled=False)
    assert result.returncode == 2
    assert "STACKCHAN_MEMORY_PATH" in result.stderr
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_cli_corrupt_db_and_invalid_preference_have_fixed_private_errors(tmp_path):
    result = run_cli(tmp_path, "set", "--minimum-speech-interval", "private-secret")
    assert result.returncode == 2
    assert "private-secret" not in result.stderr
    path = tmp_path / "folder with spaces" / "memory.sqlite3"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"private-db-secret")
    result = run_cli(tmp_path, "show")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "private-db-secret" not in result.stderr


def test_autonomy_cli_returns_failure_after_post_action_memory_fault(tmp_path):
    script = """
import os, sqlite3
from stackchan_autonomy import cli
from stackchan_autonomy.robot import FakeRobotAdapter
held = None
class LockAfterAction(FakeRobotAdapter):
    async def execute(self, command):
        global held
        await super().execute(command)
        held = sqlite3.connect(os.environ['STACKCHAN_MEMORY_PATH'])
        held.execute('BEGIN IMMEDIATE')
cli.FakeRobotAdapter = LockAfterAction
raise SystemExit(cli.main(['--cycles','1','--event','touch']))
"""
    env = dict(os.environ) | {"STACKCHAN_MEMORY_PATH": str(tmp_path / "late.sqlite3")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert "retry" in result.stderr
    assert "Traceback" not in result.stderr
