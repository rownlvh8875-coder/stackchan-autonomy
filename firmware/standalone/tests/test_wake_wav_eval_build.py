"""Compile and exercise privacy-safe offline wake WAV evaluation on Linux hosts."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_wake_wav_eval_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI provides C++20 compiler")
    root = Path(__file__).resolve().parents[1]
    include = str(root / "core")

    def compile_binary(source, name):
        binary = tmp_path / name
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
                include,
                str(source),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=90,
        )
        return binary

    fixture = compile_binary(root / "tests" / "wake_wav_eval_test.cpp", "fixture_gen")
    evaluator = compile_binary(root / "tools" / "wake_wav_eval.cpp", "wake_wav_eval")
    subprocess.run([str(fixture), str(tmp_path)], check=True, timeout=30)

    profile = str(tmp_path / "profile.swk1")
    positive = str(tmp_path / "positive.wav")
    negative = str(tmp_path / "negative.wav")
    duplicate = str(tmp_path / "duplicate.wav")
    malformed = str(tmp_path / "malformed.wav")
    before = {path: path.read_bytes() for path in tmp_path.glob("*.wav")}

    def run(*args):
        return subprocess.run(
            [str(evaluator), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=40,
        )

    success = run(profile, "--positive", positive, "--negative", negative)
    assert success.returncode == 0, success.stderr
    assert "positive_accepted=1/1" in success.stdout
    assert "negative_accepted=0/1" in success.stdout
    assert "UNVERIFIED_USER_LABELED_WAKE_EVALUATION" in success.stdout
    assert "NO device/API/install approval" in success.stdout
    assert "positive.wav" not in success.stdout
    assert "profile.swk1" not in success.stdout

    wrong_audio = run(profile, "--positive", malformed, "--negative", negative)
    assert wrong_audio.returncode == 2
    assert "REJECTED_OFFLINE" in wrong_audio.stderr
    same_audio = run(profile, "--positive", positive, "--negative", duplicate)
    assert same_audio.returncode == 2
    no_negative = run(profile, "--positive", positive)
    assert no_negative.returncode == 2
    unsupported_label = run(profile, "--other", positive, "--negative", negative)
    assert unsupported_label.returncode == 2

    for path, contents in before.items():
        assert path.read_bytes() == contents
    assert (tmp_path / "profile.swk1").is_file()
