"""Rehearse operator process boundaries without a serial device."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
OPERATOR = TOOLS / "panel_probe_operator.py"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell unavailable")
ENV = {**os.environ, "PYTHONUTF8": "1"}


def command(directory, mode):
    return [sys.executable, str(OPERATOR), mode, "--review-dir", str(directory)]


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert predicate()


@pytest.fixture
def reviewed(tmp_path):
    (tmp_path / "approval.json").write_text('{"approved":true}', encoding="utf-8")
    (tmp_path / "reviewed-trial.ps1").write_text(
        """
param([string]$Phase)
switch ($Phase) {
  'preflight' {
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'prewrite-ok.json') '{}'
  }
  'restore' {
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'restore-started.json') '{}'
    $proof = '{"independent_verify_passed":true,"metadata_matches":true}'
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'restore-verified.json') $proof
  }
  'boot-factory' {
    $proof = '{"restored_boot_requested":true,"scope_consumed":true}'
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'factory-boot-requested.json') $proof
  }
  default { exit 71 }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "run-once-and-restore.ps1").write_text(
        """
$ErrorActionPreference='Stop'
$review=$PSScriptRoot
Set-Content -LiteralPath (Join-Path $review 'install-started.json') '{}'
Write-Output '숫자가 보이면 머리 윗면에 손가락을 3초 가볍게 댄 뒤 떼세요.'
Write-Output 'private simulated transport payload'
if ($env:K151_PANEL_MOCK -eq 'interrupted') { exit 9 }
if ($env:K151_PANEL_MOCK -eq 'restore_failed') {
  Set-Content -LiteralPath (Join-Path $review 'restore-started.json') '{}'
  exit 9
}
$deadline = [DateTimeOffset]::UtcNow.AddSeconds(16)
while (-not (Test-Path -LiteralPath (Join-Path $review 'viewer-closed'))) {
  if ([DateTimeOffset]::UtcNow -ge $deadline) { exit 11 }
  Start-Sleep -Milliseconds 50
}
& (Join-Path $review 'reviewed-trial.ps1') -Phase restore
& (Join-Path $review 'reviewed-trial.ps1') -Phase boot-factory
""",
        encoding="utf-8",
    )
    return tmp_path


def test_closing_read_only_viewer_does_not_interrupt_worker_or_rollback(reviewed):
    transcript = reviewed / "mock-viewer-output.txt"
    cue = "숫자가 보이면 머리 윗면에 손가락을 3초 가볍게 댄 뒤 떼세요.".encode()
    with (
        transcript.open("wb") as view_out,
        subprocess.Popen(command(reviewed, "--view"), env=ENV, stdout=view_out) as viewer,
        subprocess.Popen(command(reviewed, "--run"), env=ENV, stdout=subprocess.PIPE) as worker,
    ):
        try:
            wait_for(lambda: cue in transcript.read_bytes())
            assert viewer.poll() is None and worker.poll() is None
            assert (reviewed / "install-started.json").exists()
            viewer.terminate()
            viewer.communicate(timeout=10)
            assert not (reviewed / "restore-started.json").exists()
            (reviewed / "viewer-closed").touch()
            out, _ = worker.communicate(timeout=15)
            assert worker.returncode == 0
        finally:
            for child in (viewer, worker):
                if child.poll() is None:
                    child.terminate()
    events = (reviewed / "panel-operator-events.log").read_text(encoding="ascii").splitlines()
    assert events == ["preflight", "installing", "PANEL_FRAME_READY", "finished"]
    assert b"private simulated transport payload" not in out
    assert b"private simulated transport payload" not in transcript.read_bytes()
    assert (reviewed / "factory-boot-requested.json").is_file()


@pytest.mark.parametrize("case", ["interrupted", "restore_failed"])
def test_child_exit_does_not_repeat_install_or_unverified_restore(reviewed, case):
    args = command(reviewed, "--run")
    result = subprocess.run(
        args,
        env={**ENV, "K151_PANEL_MOCK": case},
        capture_output=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 1
    info = json.loads((reviewed / "operator-result.json").read_bytes())
    assert info["trial_runner_exit"] == 9
    assert info["factory_restore_verified"] == (case == "interrupted")
    assert (reviewed / "factory-boot-requested.json").exists() == (case == "interrupted")
    rerun = subprocess.run(args, env=ENV, timeout=10, check=False, capture_output=True)
    assert rerun.returncode == 2


def test_without_review_approval_worker_never_invokes_scripts(reviewed):
    (reviewed / "approval.json").unlink()
    failure = subprocess.run(
        command(reviewed, "--run"), env=ENV, timeout=10, check=False, capture_output=True
    )
    assert failure.returncode == 2
    assert not (reviewed / "prewrite-ok.json").exists()
    assert not (reviewed / "panel-operator-events.log").exists()
