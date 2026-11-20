"""Offline robust wake gates: calibration-only, never final evaluation peeking."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def experiment(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    source = ROOT / "tools" / "experiment_wake_trim_calibration.py"
    spec = importlib.util.spec_from_file_location(source.stem, source)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_calibration_reader_never_opens_previous_evaluation_wavs(experiment, monkeypatch):
    original = experiment._read_bounded
    accessed = []

    def guarded(path, bound):
        path = Path(path)
        assert "evaluation" not in path.parts
        accessed.append(path)
        return original(path, bound)

    monkeypatch.setattr(experiment, "_read_bounded", guarded)
    rows = experiment.calibration_only_records()
    assert {key: len(value) for key, value in rows.items()} == {
        "enroll": 1,
        "positive": 5,
        "negative": 10,
    }
    assert len(accessed) == 16


def test_freeze_gates_reject_false_positive_or_incomplete_calibration(experiment):
    good = {
        "status": "training_only_diagnostics",
        "conditions": {
            key: {
                "positive": {"accepted": 5, "total": 5},
                "negative": {"accepted": 0, "total": 10},
            }
            for key in ("clean", "gain_half", "noise_20db", "noise_10db", "echo_80ms")
        },
    }
    assert experiment.frozen_dev_gates_pass(good)
    assert not experiment.frozen_dev_gates_pass({"status": "calibration_rejected"})
    for condition in tuple(good["conditions"]):
        corrupted = {
            "status": "training_only_diagnostics",
            "conditions": {
                k: {name: dict(data) for name, data in metrics.items()}
                for k, metrics in good["conditions"].items()
            },
        }
        corrupted["conditions"][condition]["negative"]["accepted"] = 1
        assert not experiment.frozen_dev_gates_pass(corrupted)
        corrupted["conditions"][condition]["negative"]["accepted"] = 0
        corrupted["conditions"][condition]["positive"]["accepted"] = 4
        assert not experiment.frozen_dev_gates_pass(corrupted)


def test_experimental_flag_is_host_only_and_hardware_hold_stays_off():
    encoder = (ROOT / "tools" / "wake_wav_enroll.cpp").read_text(encoding="utf-8")
    matcher = (ROOT / "tools" / "wake_wav_eval.cpp").read_text(encoding="utf-8")
    feature = (ROOT / "core" / "offline_wake_feature.hpp").read_text(encoding="utf-8")
    hold = (ROOT / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "offline_wake_extract(*pcm)" in encoder
    assert "offline_wake_extract(*samples)" in matcher
    assert "#ifdef STACKCHAN_EXPERIMENTAL_WAKE_TRIM" in feature
    assert "#else" in feature
    assert "return wake_mfcc_from_24k(pcm);" in feature
    assert "offline_wake_feature.hpp" not in hold
    assert "offline_wake_trim.hpp" not in hold


def test_trim_host_cpp(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++20 g++ unavailable; Linux CI supplies compiler")
    output = tmp_path / "offline_wake_trim"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(ROOT / "core"),
            str(ROOT / "tests" / "offline_wake_trim_test.cpp"),
            "-o",
            str(output),
        ],
        check=True,
        timeout=100,
        capture_output=True,
    )
    subprocess.run([str(output)], check=True, timeout=30)
