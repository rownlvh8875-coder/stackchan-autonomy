"""Run the real one-shot diagnostic entry point with fake SDK/codec callbacks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def entrypoint(tmp_path_factory):
    return _build_entrypoint(tmp_path_factory, question=False)


@pytest.fixture(scope="module")
def question_entrypoint(tmp_path_factory):
    return _build_entrypoint(tmp_path_factory, question=True)


def _build_entrypoint(tmp_path_factory, *, question):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("mic-wake-entry") / "entry"
    built = subprocess.run(
        [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread"]
        + (["-DSTACKCHAN_K151_QUESTION_TRIAL=1"] if question else [])
        + [
            arg
            for include in (
                "tests/board_probe_doubles",
                "core",
                "esp_app/main",
                "resource_bench/main",
            )
            for arg in ("-I", str(BASE / include))
        ]
        + [
            str(BASE / "mic_wake_trial/main/app_main.cpp"),
            str(BASE / "tests/mic_wake_entrypoint_test.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "detect",
        "missing",
        "slot",
        "size",
        "type",
        "subtype",
        "chip",
        "revision",
        "bad_nonce",
        "stop_before",
        "no_hello",
        "stop_during",
        "usb_error",
        "task_error",
    ],
)
def test_one_shot_mic_entrypoint(entrypoint, case, monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from wake_bench_trace import parse_mic_wake_trial_report

    done = subprocess.run([str(entrypoint), case], capture_output=True, text=True, timeout=8)
    assert done.returncode == 0, done.stderr
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    if case in {"detect", "stop_during"}:
        assert [event.get("mic_trial", event.get("mic_wake_trial")) for event in events] == [
            "WAIT_LOCAL_START",
            "LISTEN_NOW",
            "MIC_WAKE_TRIAL_V2",
            "HOLD_UNTIL_RESET",
        ]
        report = parse_mic_wake_trial_report(events[2])
        if case == "detect":
            assert report["result"] == "detected" and report["frames_read"] == 4
        else:
            assert report["result"] == "stopped" and "frames_read" not in report
    else:
        assert not any(event.get("mic_trial") == "LISTEN_NOW" for event in events)
        assert not any("frames_read" in event for event in events)
        assert events[-1] == {"mic_trial": "HOLD_UNTIL_RESET", "operating_admission": False}


@pytest.mark.parametrize("case", ["detect", "stop_during", "quiet_timeout", "bad_nonce", "slot"])
def test_question_trial_entrypoint(question_entrypoint, case):
    done = subprocess.run(
        [str(question_entrypoint), case], capture_output=True, text=True, timeout=8
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("K151_RECEIVE_ONLY_QUESTION_TRIAL_NOT_OPERATIONAL\n")
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    assert all(event.get("mic_trial") != "WAIT_LOCAL_START" for event in events)
    assert events[-1] == {"mic_trial": "HOLD_UNTIL_RESET", "operating_admission": False}
    if case in {"bad_nonce", "slot"}:
        assert not any("mic_question_trial" in event for event in events)
    else:
        assert events[0]["mic_trial"] == "WAIT_QUESTION_LOCAL_START"
        assert events[1]["mic_trial"] == "LISTEN_NOW"
        assert any("mic_wake_trial" in event for event in events)
        assert events[-2] == {
            "mic_question_trial": "MIC_QUESTION_TRIAL_V1",
            "result": {
                "detect": "endpoint",
                "stop_during": "not_run",
                "quiet_timeout": "quiet_timeout",
            }[case],
            "codec_cleanup_unverified": False,
            "operating_admission": False,
        }
    assert sum(event.get("mic_trial") == "QUESTION_NOW" for event in events) == (case == "detect")
