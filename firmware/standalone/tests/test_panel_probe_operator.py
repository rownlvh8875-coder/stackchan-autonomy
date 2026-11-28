"""Rehearse operator process boundaries without a serial device."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_collect_mic_wake_trial import AUTO_STOP_REPORT

TOOLS = Path(__file__).resolve().parents[1] / "tools"
OPERATOR = TOOLS / "panel_probe_operator.py"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell unavailable")
ENV = {**os.environ, "PYTHONUTF8": "1"}
SPEAKER_CUES = ["SPEAKER_STOP_PREPARE", "SPEAKER_STOP_PLAYING", "SPEAKER_STOP_WINDOW_CLOSED"]
HEARD_STOP = "heard_stop"


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
if ($env:K151_PANEL_MOCK -eq 'speaker') {
  Write-Output 'SPEAKER_PREPARE'
} else {
  Write-Output '숫자가 보이면 머리 윗면에 손가락을 3초 가볍게 댄 뒤 떼세요.'
}
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


@pytest.mark.parametrize(
    ("mock", "cue", "marker"),
    [
        (
            "panel",
            "숫자가 보이면 머리 윗면에 손가락을 3초 가볍게 댄 뒤 떼세요.",
            "PANEL_FRAME_READY",
        ),
        ("speaker", "로봇에서 짧은 삐 소리가 나는지 들어 주세요.", "SPEAKER_PREPARE"),
    ],
)
def test_closing_read_only_viewer_does_not_interrupt_worker_or_rollback(
    reviewed, mock, cue, marker
):
    transcript = reviewed / "mock-viewer-output.txt"
    env = {**ENV, "K151_PANEL_MOCK": mock}
    with (
        transcript.open("wb") as view_out,
        subprocess.Popen(command(reviewed, "--view"), env=ENV, stdout=view_out) as viewer,
        subprocess.Popen(command(reviewed, "--run"), env=env, stdout=subprocess.PIPE) as worker,
    ):
        try:
            wait_for(lambda: cue.encode() in transcript.read_bytes())
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
    assert events == ["preflight", "installing", marker, "finished"]
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


def test_manual_speaker_view_prompts_once_then_closes_and_recovers(reviewed):
    (reviewed / "run-once-and-restore.ps1").write_text(
        """
$review=$PSScriptRoot
Set-Content -LiteralPath (Join-Path $review 'install-started.json') '{}'
Write-Output 'SPEAKER_STOP_PREPARE'
Write-Output 'SPEAKER_STOP_PLAYING'
Write-Output 'SPEAKER_STOP_PLAYING'
$deadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath (Join-Path $review 'viewer-closed'))) {
  if ([DateTimeOffset]::UtcNow -ge $deadline) { exit 11 }
  Start-Sleep -Milliseconds 50
}
Write-Output 'SPEAKER_STOP_WINDOW_CLOSED'
Write-Output 'SPEAKER_STOP_PLAYING'
Write-Output 'flash-id-before-restore exit=0'
Write-Output 'SPEAKER_STOP_PLAYING'
exit 9
""",
        encoding="utf-8",
    )
    transcript = reviewed / "mock-viewer-output.txt"
    with (
        transcript.open("wb") as view_out,
        subprocess.Popen(command(reviewed, "--view"), env=ENV, stdout=view_out) as viewer,
        subprocess.Popen(command(reviewed, "--run"), env=ENV, stdout=subprocess.PIPE) as worker,
    ):
        try:
            cue = "삐 소리가 들리는 동안 로봇 앞면 화면을 한 번만 가볍게 터치하세요.".encode()
            wait_for(lambda: cue in transcript.read_bytes())
        finally:
            (reviewed / "viewer-closed").touch()
            worker.communicate(timeout=18)
            viewer.communicate(timeout=8)
    assert transcript.read_bytes().count(cue) == 1
    events = (reviewed / "panel-operator-events.log").read_text(encoding="ascii").splitlines()
    assert events.count("SPEAKER_STOP_PLAYING") == 1
    assert events[2:5] == SPEAKER_CUES
    assert (reviewed / "factory-boot-requested.json").exists()


@pytest.mark.parametrize(
    ("observation", "case", "passed"),
    [
        (HEARD_STOP, "manual", True),
        ("no_tone", "manual", False),
        ("continued", "manual", False),
        ("unclear", "manual", False),
        (HEARD_STOP, "host_stopped", False),
        (HEARD_STOP, "full_queue", False),
        (HEARD_STOP, "no_cue", False),
        (HEARD_STOP, "late_cue", False),
        (HEARD_STOP, "collector_failed", False),
        (HEARD_STOP, "fallback", False),
        (HEARD_STOP, "auto_review", None),
        (HEARD_STOP, "restore_failed", None),
    ],
)
def test_listening_result_requires_one_bound_manual_trial_and_restoration(
    reviewed, observation, case, passed
):
    digest = "a" * 64
    scope = "ONE_SYNTHETIC_SPEAKER_SCREEN_STOP_AND_OTA1_RESTORE"
    mode = "SYNTHETIC_SPEAKER_SCREEN_STOP"
    binding = {"image_sha256": digest, "review_id": reviewed.name}
    records = {
        "review-manifest": binding
        | {
            "port": "COM7",
            "operator_mode": mode,
            "kind": "REVIEW_ONLY_SPEAKER_STOP_V3",
            "expected_protocol": "K151_SPEAKER_STOP_V3",
            "scope": scope,
        },
        "approval": binding | {"approved": True, "scope": scope, "operator_mode": mode},
        "install-verified": binding
        | {"independent_verify_passed": True, "offset": 0x510000, "port": "COM7"},
        "mic-receive-intent": {"image_sha256": digest},
        "operator-result": {
            "preflight_exit": 0,
            "trial_runner_exit": 0,
            "fallback_recovery_exit": None,
            "factory_restore_verified": True,
        },
        "speaker-result": AUTO_STOP_REPORT
        | {
            "result": "screen_stop_and_standby_observed",
            "sample_to_standby_us": 5_000,
            "stop_diagnostic": AUTO_STOP_REPORT["stop_diagnostic"] | {"screen_stop_sampled": True},
        },
        "restore-verified": {"independent_verify_passed": True, "metadata_matches": True},
        "factory-boot-requested": {"restored_boot_requested": True, "scope_consumed": True},
    }
    if case == "auto_review":
        records["approval"]["operator_mode"] = "SYNTHETIC_SPEAKER_AUTOMATIC_STOP"
    elif case == "host_stopped":
        records["speaker-result"] = AUTO_STOP_REPORT
    elif case == "full_queue":
        records["speaker-result"]["pcm_blocks"] = 250
    elif case == "collector_failed":
        records["operator-result"]["trial_runner_exit"] = 1
    elif case == "fallback":
        records["operator-result"]["fallback_recovery_exit"] = 0
    elif case == "restore_failed":
        records["restore-verified"]["independent_verify_passed"] = False
    for file, data in records.items():
        (reviewed / f"{file}.json").write_text(json.dumps(data), encoding="utf-8")
    events = ["preflight", "installing", *SPEAKER_CUES, "restoring", "finished"]
    if case == "no_cue":
        events.remove("SPEAKER_STOP_PLAYING")
    elif case == "late_cue":
        events.remove("restoring")
        events.insert(3, "restoring")
    (reviewed / "panel-operator-events.log").write_text("\n".join(events) + "\n", encoding="ascii")
    args = command(reviewed, f"--record-listening={observation}")
    trial = subprocess.run(args, env=ENV, timeout=10, check=False, capture_output=True)
    evidence = reviewed / "speaker-screen-audible-result.json"
    if passed is None:
        assert trial.returncode == 2
        assert not evidence.exists()
        return
    assert trial.returncode == (0 if passed else 1)
    result = json.loads(evidence.read_bytes())
    assert result["functional_stop_confirmed"] is passed
    assert result["listening_observation"] == observation
    assert result["electrical_stop_mute_verified"] is False
    repeated = subprocess.run(args, env=ENV, timeout=10, check=False, capture_output=True)
    assert repeated.returncode == 2
