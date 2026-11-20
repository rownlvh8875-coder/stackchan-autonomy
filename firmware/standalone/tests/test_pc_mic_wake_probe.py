"""Local-only SWK1 recognition through a byte-bounded stdin WAV stream.

Host C++ tests can run on Linux CI. No microphone device, robot or network.
"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
PROFILE = BASE / "fixtures" / "korean_josu_sapi_20261120" / "josu-20261120.swk1"
FIXTURE = BASE / "fixtures" / "korean_josu_sapi_20261120"


@pytest.fixture(scope="module")
def probe_exe(tmp_path_factory):
    # Windows bench can reuse a locally built native probe without downloading a toolchain.
    supplied = os.environ.get("STACKCHAN_TEST_WAKE_PROBE_EXE")
    if supplied:
        path = Path(supplied)
        assert path.is_file() and not path.is_symlink()
        return path
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Native stdin probe integration runs on Linux CI; Windows uses pinned Zig")
    binary = tmp_path_factory.mktemp("pc-wake-probe") / "wake-probe"
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
            str(TOOLS / "wake_stage1_probe.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    return binary


@pytest.fixture
def python_probe(monkeypatch):
    tool = TOOLS / "pc_mic_wake_probe.py"
    spec = importlib.util.spec_from_file_location("pc_mic_wake_probe", tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["evaluation_wake_01.wav", "evaluation_wake_02.wav"])
def test_new_josu_wav_accepted_from_stdin(probe_exe, name):
    path = FIXTURE / "evaluation" / name
    result = subprocess.run(
        [str(probe_exe), str(PROFILE), "-"],
        input=path.read_bytes(),
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == b"OFFLINE_STAGE1_ACCEPT"
    assert result.stderr == b""


@pytest.mark.parametrize(
    "name",
    [f"evaluation_nonwake_{n:02}.wav" for n in range(1, 7)],
)
def test_nonwake_including_former_phrase_rejected(probe_exe, name):
    path = FIXTURE / "evaluation" / name
    result = subprocess.run(
        [str(probe_exe), str(PROFILE), "-"],
        input=path.read_bytes(),
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == b"OFFLINE_STAGE1_REJECT"


@pytest.mark.parametrize("payload", [b"", b"\x00" * 200, b"RIFF" + b"\x00" * 300, b"z" * 196609])
def test_bounded_stream_fail_closed_no_audio_echo(probe_exe, payload):
    result = subprocess.run(
        [str(probe_exe), str(PROFILE), "-"],
        input=payload,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.strip() == b"OFFLINE_WAKE_PROBE_REJECTED"


def test_original_file_argument_still_works(probe_exe):
    path = FIXTURE / "evaluation" / "evaluation_wake_01.wav"
    result = subprocess.run(
        [str(probe_exe), str(PROFILE), str(path)],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == b"OFFLINE_STAGE1_ACCEPT"


def test_python_fixture_runner_no_mic_and_no_cloud(probe_exe):
    path = FIXTURE / "evaluation" / "evaluation_wake_01.wav"
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "pc_mic_wake_probe.py"),
            "--probe-exe",
            str(probe_exe),
            "--profile",
            str(PROFILE),
            "--fixture",
            str(path),
        ],
        capture_output=True,
        timeout=20,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "UNVERIFIED_MATCH"
    assert output["source"] == "EXISTING_LOCAL_FIXTURE"
    assert not output["k151_microphone_verified"]
    assert not output["recorded_audio_written_to_disk"]
    assert not output["network_or_paid_api_used"]


def test_microphone_requires_explicit_device_and_cannot_start_from_import(
    python_probe, tmp_path, capsys
):
    # Import contains no recording. The missing device fails BEFORE any audio import.
    assert capsys.readouterr().out == ""
    dummy = tmp_path / "wake.exe"
    dummy.write_bytes(b"not-executable")
    code = python_probe.main(["--probe-exe", str(dummy), "--profile", str(PROFILE), "--listen"])
    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "explicit_input_device_required"
    assert not output["k151_hardware_accessed"]
    assert not output["network_or_paid_api_used"]


def test_python_runner_rejects_invalid_fixture_size_without_running_tool(
    python_probe, tmp_path, capsys
):
    dummy = tmp_path / "probe.exe"
    dummy.write_bytes(b"some bytes")
    wav = tmp_path / "oversized.wav"
    wav.write_bytes(b"z" * 196609)
    rc = python_probe.main(
        [
            "--probe-exe",
            str(dummy),
            "--profile",
            str(PROFILE),
            "--fixture",
            str(wav),
        ]
    )
    assert rc == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "missing_or_invalid_local_file"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        *[(f"evaluation_nonwake_{n:02}.wav", "UNVERIFIED_NO_MATCH") for n in range(1, 7)],
        ("evaluation_wake_01.wav", "UNVERIFIED_MATCH"),
        ("evaluation_wake_02.wav", "UNVERIFIED_MATCH"),
    ],
)
def test_optional_48khz_microphone_path_with_synthetic_silence(
    probe_exe, python_probe, name, expected
):
    """Development regression only; synthetic same-voice WAV is not human acoustic proof."""
    np = pytest.importorskip("numpy")
    path = FIXTURE / "evaluation" / name
    with wave.open(str(path), "rb") as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (
            24000,
            1,
            2,
        )
        raw = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    # 200ms silence around a doubled PCM16 fixture simulates 48kHz capture.
    pad = np.zeros(9600, dtype=np.int16)
    mic48 = np.concatenate((pad, np.repeat(raw, 2), pad)).astype(np.int16)
    trimmed = python_probe.resample_and_trim_48k(mic48, np)
    assert trimmed is not None
    try:
        target = io.BytesIO()
        with wave.open(target, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(trimmed.astype("<i2", copy=False).tobytes())
        assert python_probe.classify_wav(probe_exe, PROFILE, target.getvalue()) == expected
    finally:
        trimmed.fill(0)
        mic48.fill(0)


def test_optional_48khz_silence_is_never_a_wake(python_probe):
    np = pytest.importorskip("numpy")
    silent = np.zeros(120000, dtype=np.int16)
    assert python_probe.resample_and_trim_48k(silent, np) is None
