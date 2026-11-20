"""Regression: explicitly shared synthetic Heami WAV / SWK1 fixtures only."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
FIXTURE = BASE / "fixtures" / "korean_heami_sapi_20261120"
PROFILE = FIXTURE / "heami-korean-offline-zig.swk1"


def _load(name):
    tool = BASE / "tools" / name
    spec = importlib.util.spec_from_file_location(tool.stem, tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_synthetic_assets_integrity_and_group_counts(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from scfg_offline import validate_profile
    from wake_corpus_audit import inspect_corpus

    lines = (FIXTURE / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 26
    listed = set()
    for line in lines:
        sha256, path = line.split("  ", maxsplit=1)
        assert len(sha256) == 64
        assert path not in listed
        assert not path.startswith("/") and ".." not in Path(path).parts
        listed.add(path)
        asset = FIXTURE / path
        assert asset.is_file() and not asset.is_symlink()
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == sha256

    audio = sorted(FIXTURE.rglob("*.wav"))
    assert len(audio) == 24
    assert set(str(f.relative_to(FIXTURE)).replace("\\", "/") for f in audio) == {
        entry for entry in listed if entry.endswith(".wav")
    }
    assert listed == {
        *(str(path.relative_to(FIXTURE)).replace("\\", "/") for path in audio),
        "heami-korean-offline-zig.swk1",
        "synthetic-sapi.wake-corpus.json",
    }
    assert validate_profile(PROFILE.read_bytes()) == 1
    assert PROFILE.stat().st_size == 843
    with (FIXTURE / "synthetic-sapi.wake-corpus.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    assert len(manifest["samples"]) == 24
    for row in manifest["samples"]:
        with wave.open(str(FIXTURE / row["file"]), "rb") as f:
            assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (1, 2, 24000)
            assert 2400 <= f.getnframes() <= 72000
    review = inspect_corpus(FIXTURE / "synthetic-sapi.wake-corpus.json")
    assert review["status"] == "CORPUS_STRUCTURALLY_SCREENED"
    assert review["counts"] == {
        "enrollment_wake": 1,
        "calibration_wake": 5,
        "calibration_nonwake": 10,
        "evaluation_wake": 2,
        "evaluation_nonwake": 6,
    }
    assert review["screening_warnings"] == {}
    assert not review["korean_wake_accuracy_proven"]
    assert not review["safe_to_install"]
    assert not list(FIXTURE.rglob("*.exe"))
    assert not list(FIXTURE.rglob("*.pdb"))


def test_robustness_transform_is_deterministic_and_bounded(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from evaluate_synthetic_robustness import (
        CONDITIONS,
        RobustnessError,
        load_public_evaluation,
        perturb,
    )

    samples = load_public_evaluation(FIXTURE)
    assert len(samples) == 8
    assert sum(x["label"] == "wake" for x in samples) == 2
    assert sum(x["label"] == "nonwake" for x in samples) == 6
    pcm = samples[0]["pcm"]
    assert len(CONDITIONS) == 8
    for condition in CONDITIONS:
        result = perturb(pcm, condition, samples[0]["id"])
        assert len(result) == len(pcm)
        assert result == perturb(pcm, condition, samples[0]["id"])
        if condition != "clean":
            assert result != pcm
    with pytest.raises(RobustnessError, match="unknown_perturbation"):
        perturb(pcm, "unsupported", samples[0]["id"])


def test_real_cpp_robustness_evaluation_on_shared_fixture(monkeypatch, tmp_path):
    """Linux CI actually runs the C++ MFCC/DTW matching on committed WAVs."""
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("g++ unavailable; Linux CI supplies native C++20 compiler")
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from evaluate_synthetic_robustness import evaluate

    binary = tmp_path / "wake_wav_eval"
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
            str(BASE / "core"),
            str(BASE / "tools" / "wake_wav_eval.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    report = evaluate(FIXTURE, PROFILE, binary)
    assert report["status"] == "SYNTHETIC_ROBUSTNESS_EXPERIMENT_NOT_HARDWARE_PROOF"
    assert set(report["conditions"]) == {
        "clean",
        "gain_half",
        "noise_20db",
        "noise_10db",
        "noise_5db",
        "noise_0db",
        "echo_80ms",
        "echo_160ms",
    }
    for result in report["conditions"].values():
        assert result["positive"]["total"] == 2
        assert result["negative"]["total"] == 6
    assert not report["actual_korean_wake_accuracy_proven"]
    assert not report["device_install_authorized"]
    assert not report["network_or_paid_api_used"]
    assert not report["physical_robot_tested"]
