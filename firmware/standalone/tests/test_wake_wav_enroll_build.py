"""Compile and exercise private WAV -> SWK1 offline calibration, fake tones only."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_wake_wav_enroll_host(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable; Linux CI provides C++20 compiler")
    root = Path(__file__).resolve().parents[1]

    def compile_cpp(relative, name):
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
                str(root / "core"),
                str(root / relative),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=90,
        )
        return binary

    fixture = compile_cpp("tests/wake_wav_enroll_fixture.cpp", "fixture_generator")
    enrollment = compile_cpp("tools/wake_wav_enroll.cpp", "wake_wav_enroll")
    evaluator = compile_cpp("tools/wake_wav_eval.cpp", "wake_wav_eval")
    subprocess.run([str(fixture), str(tmp_path)], check=True, timeout=30)

    template = tmp_path / "template.wav"
    holdouts = [tmp_path / f"holdout_{i}.wav" for i in range(5)]
    negatives = [tmp_path / f"negative_{i}.wav" for i in range(10)]
    profile = tmp_path / "private.swk1"

    args = ["--template", str(template)]
    for sample in holdouts:
        args.extend(["--holdout", str(sample)])
    for sample in negatives:
        args.extend(["--negative", str(sample)])

    def invoke(*more):
        return subprocess.run(
            [str(enrollment), *more],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    created = invoke(*args, "--output", str(profile))
    assert created.returncode == 0, created.stderr
    assert "UNVERIFIED_PRIVATE_WAKE_PROFILE_WRITTEN" in created.stdout
    assert "template_count=1 holdout_count=5 negative_count=10" in created.stdout
    assert not any(x.name in created.stdout for x in tmp_path.iterdir())
    assert "NO device/API/install approval" in created.stdout
    contents = profile.read_bytes()
    assert contents[:4] == b"SWK1" and len(contents) == 11 + 64 * 13
    if os.name == "posix":
        assert profile.stat().st_mode & 0o077 == 0

    smoke = subprocess.run(
        [
            str(evaluator),
            str(profile),
            "--positive",
            str(holdouts[0]),
            "--negative",
            str(negatives[0]),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert smoke.returncode == 0, smoke.stderr
    assert "positive_accepted=1/1" in smoke.stdout
    assert "negative_accepted=0/1" in smoke.stdout

    # Exclusive file creation; never overwrite an already enrolled profile.
    repeated = invoke(*args, "--output", str(profile))
    assert repeated.returncode == 2
    assert profile.read_bytes() == contents

    duplicate = invoke(
        "--template",
        str(template),
        "--holdout",
        str(tmp_path / "duplicate.wav"),
        *args[2:],
        "--output",
        str(tmp_path / "duplicate.swk1"),
    )
    assert duplicate.returncode == 2
    assert not (tmp_path / "duplicate.swk1").exists()

    bad_file = invoke(
        "--template",
        str(tmp_path / "corrupt.wav"),
        "--output",
        str(tmp_path / "corrupt.swk1"),
    )
    assert bad_file.returncode == 2
    assert not (tmp_path / "corrupt.swk1").exists()

    no_holdouts = invoke("--template", str(template), "--output", str(tmp_path / "bad.swk1"))
    assert no_holdouts.returncode == 2
    assert not (tmp_path / "bad.swk1").exists()

    no_speech = invoke(
        "--template",
        str(tmp_path / "silent.wav"),
        "--output",
        str(tmp_path / "silent.swk1"),
    )
    assert no_speech.returncode == 2
    assert not (tmp_path / "silent.swk1").exists()
