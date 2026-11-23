"""Supervise the reviewed K151 panel trial and show independent local cues."""

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from collect_panel_probe import STAGES

EVENTS_FILE = "panel-operator-events.log"
RESULT_FILE = "operator-result.json"
INSTALL_MARKER = "install-started.json"
RESTORE_MARKERS = ("restore-started.json", "restore-verified.json", "factory-boot-requested.json")
CUES = {
    "preflight": "장치와 원본을 확인 중입니다.",
    "installing": "이미지 검증을 기다려 주세요.",
    "restoring": "원본 펌웨어를 복구 중입니다. USB를 연결한 채로 두세요.",
    "finished": "진단 작업이 종료됐습니다.",
    **STAGES,
}
COLLECTOR_CUES = {message: name for name, message in STAGES.items()}


def run_powershell(shell, script, args, publish):
    with subprocess.Popen(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    ) as process:
        for line in process.stdout:
            cue = COLLECTOR_CUES.get(line.rstrip())
            if cue:
                publish(cue)
            elif line.startswith("flash-id-before-restore exit="):
                publish("restoring")
        return process.wait()


def factory_restore_verified(directory):
    try:
        restore = json.loads((directory / "restore-verified.json").read_bytes())
        boot = json.loads((directory / "factory-boot-requested.json").read_bytes())
        return all(
            record.get(field) is True
            for record, field in (
                (restore, "independent_verify_passed"),
                (restore, "metadata_matches"),
                (boot, "restored_boot_requested"),
                (boot, "scope_consumed"),
            )
        )
    except (OSError, ValueError, AttributeError):
        return False


def supervise(directory, shell):
    phase = directory / "reviewed-trial.ps1"
    trial = directory / "run-once-and-restore.ps1"
    if not all(path.is_file() for path in (phase, trial, directory / "approval.json")) or any(
        (directory / name).exists()
        for name in ("prewrite-ok.json", INSTALL_MARKER, RESULT_FILE, *RESTORE_MARKERS)
    ):
        return 2
    try:
        events = (directory / EVENTS_FILE).open("x", encoding="ascii", newline="\n")
    except OSError:
        return 2

    def publish(cue):
        # Presentation failure cannot cancel the device worker.
        try:
            events.write(cue + "\n")
            events.flush()
        except OSError:
            pass

    preflight_exit = trial_exit = recovery_exit = None
    try:
        publish("preflight")
        preflight_exit = run_powershell(shell, phase, ["-Phase", "preflight"], publish)
        if preflight_exit == 0:
            publish("installing")
            trial_exit = run_powershell(shell, trial, [], publish)
        # If the child exited abruptly, recover only an untouched recovery attempt.
        # The reviewed script checks the same board and files before any write.
        if (directory / INSTALL_MARKER).exists() and not any(
            (directory / name).exists() for name in RESTORE_MARKERS
        ):
            publish("restoring")
            recovery_exit = run_powershell(shell, phase, ["-Phase", "restore"], publish)
            if recovery_exit == 0:
                recovery_exit = run_powershell(shell, phase, ["-Phase", "boot-factory"], publish)
        restored = factory_restore_verified(directory)
        result = {
            "preflight_exit": preflight_exit,
            "trial_runner_exit": trial_exit,
            "fallback_recovery_exit": recovery_exit,
            "factory_restore_verified": restored,
        }
        with (directory / RESULT_FILE).open("x", encoding="utf-8") as out:
            json.dump(result, out)
        print(json.dumps(result), flush=True)
        if preflight_exit != 0:
            return 2
        return 0 if trial_exit == 0 and restored else 1
    finally:
        publish("finished")
        events.close()


def show_cues(directory):
    print("StackChan K151 화면·머리 터치·STOP 안내를 기다리는 중입니다.", flush=True)
    deadline = time.monotonic() + 360
    displayed = None
    while time.monotonic() < deadline:
        try:
            with (directory / EVENTS_FILE).open("rb") as stream:
                data = stream.read(1025)
        except FileNotFoundError:
            data = b""
        if len(data) > 1024:
            return 1
        lines = data.split(b"\n")[:-1]
        # Show the newest complete state so a reopened viewer skips stale cues.
        if lines and lines[-1] != displayed:
            displayed = lines[-1]
            cue = displayed.decode("ascii", errors="replace")
            if cue in CUES:
                print(CUES[cue], flush=True)
            if cue == "finished":
                return 0
        time.sleep(0.05)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--view", action="store_true")
    parser.add_argument("--review-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.review_dir.resolve()
    if args.view:
        return show_cues(directory)
    shell = shutil.which("pwsh")
    return supervise(directory, shell) if shell else 2


if __name__ == "__main__":
    raise SystemExit(main())
