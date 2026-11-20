"""Synthetic '조수' wake fixtures: host regression only, never hardware proof."""

import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
FIXTURE = BASE / "fixtures" / "korean_josu_sapi_20261120"
PROFILE = FIXTURE / "josu-20261120.swk1"


def test_josu_fixture_integrity_and_structural_screen(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from scfg_offline import validate_profile
    from wake_corpus_audit import inspect_corpus

    # Hashed JSON must remain raw-LF on every OS, including Windows checkout.
    manifest_bytes = (FIXTURE / "synthetic-sapi.wake-corpus.json").read_bytes()
    assert b"\r\n" not in manifest_bytes
    lines = (FIXTURE / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 26
    listed = set()
    for line in lines:
        digest, name = line.split("  ", maxsplit=1)
        assert name not in listed and not name.startswith("/") and ".." not in Path(name).parts
        listed.add(name)
        file = FIXTURE / name
        assert file.is_file() and not file.is_symlink()
        assert hashlib.sha256(file.read_bytes()).hexdigest() == digest
    wavs = sorted(FIXTURE.rglob("*.wav"))
    assert len(wavs) == 24
    assert listed == {
        *(x.relative_to(FIXTURE).as_posix() for x in wavs),
        PROFILE.name,
        "synthetic-sapi.wake-corpus.json",
    }
    assert validate_profile(PROFILE.read_bytes()) == 1
    assert PROFILE.stat().st_size == 843
    assert hashlib.sha256(PROFILE.read_bytes()).hexdigest() == (
        "72c73795a7db475d8dbf979040021f318d2ede418d7d0d5aa9e29832a9193591"
    )
    manifest = json.loads((FIXTURE / "synthetic-sapi.wake-corpus.json").read_text(encoding="utf-8"))
    assert len(manifest["samples"]) == 24
    for item in manifest["samples"]:
        with wave.open(str(FIXTURE / item["file"]), "rb") as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)
    audit = inspect_corpus(FIXTURE / "synthetic-sapi.wake-corpus.json")
    assert audit["status"] == "CORPUS_STRUCTURALLY_SCREENED"
    assert audit["counts"] == {
        "enrollment_wake": 1,
        "calibration_wake": 5,
        "calibration_nonwake": 10,
        "evaluation_wake": 2,
        "evaluation_nonwake": 6,
    }
    assert not audit["screening_warnings"]
    assert not audit["korean_wake_accuracy_proven"]
    assert not audit["safe_to_install"]


def test_josu_cpp_mfcc_clean_evaluation(monkeypatch, tmp_path):
    """Independent host C++ runtime re-evaluates labeled synthetic clips."""
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Linux CI supplies g++ C++20")
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
    assert report["conditions"]["clean"]["positive"] == {"accepted": 2, "total": 2}
    assert report["conditions"]["clean"]["negative"] == {"accepted": 0, "total": 6}
    assert not report["actual_korean_wake_accuracy_proven"]
    assert not report["device_install_authorized"]
    assert not report["physical_robot_tested"]
