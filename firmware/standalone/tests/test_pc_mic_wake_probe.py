"""Local-only SWK1 recognition through a byte-bounded stdin WAV stream.

Host C++ tests can run on Linux CI. No microphone device, robot or network.
"""

import importlib.util
import io
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
PROFILE = BASE / "fixtures" / "korean_josu_sapi_20261120" / "josu-20261120.swk1"
FIXTURE = BASE / "fixtures" / "korean_josu_sapi_20261120"


@pytest.fixture
def python_probe(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
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


def test_score_reports_actual_distance_and_limit_without_audio_or_features(probe_exe):
    profile = PROFILE.read_bytes()
    wav = (FIXTURE / "evaluation" / "evaluation_wake_01.wav").read_bytes()
    result = subprocess.run(
        [str(probe_exe), "--score", "-"],
        input=len(profile).to_bytes(2, "big") + profile + wav,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    score = json.loads(result.stdout)
    assert score["accepted"] is True
    assert 0 <= score["distance_q8"] < score["limit_q8"]
    assert score["limit_q8"] == int.from_bytes(profile[5:7], "little")
    assert set(score) == {"accepted", "distance_q8", "limit_q8"}


def test_feature_pipe_uses_original_mfcc_and_calibrates_in_memory(probe_exe):
    wav = (FIXTURE / "enrollment" / "enrollment_wake_01.wav").read_bytes()
    result = subprocess.run(
        [str(probe_exe), "--features", "-"], input=wav, capture_output=True, timeout=20
    )
    assert result.returncode == 0 and len(result.stdout) == 832 and result.stderr == b""
    # The published profile's first template is the exact feature of this public WAV.
    assert result.stdout == PROFILE.read_bytes()[7:839]
    # Hand-chosen distinguishable features exercise the real C++ calibrator's gate.
    features = b"".join(bytes([n]) * 832 for n in [0, 1, 2, 3, 4, 5, 6, 7, *range(70, 80)])
    result = subprocess.run(
        [str(probe_exe), "--calibrate", "-"], input=features, capture_output=True, timeout=20
    )
    assert result.returncode == 0 and result.stdout.startswith(b"SWK1\x03")
    assert len(result.stdout) == 2507
    duplicated = bytes(832 * 18)
    result = subprocess.run(
        [str(probe_exe), "--calibrate", "-"], input=duplicated, capture_output=True, timeout=20
    )
    assert result.returncode == 2 and not result.stdout


@pytest.mark.parametrize(
    ("mode", "body"),
    [
        ("--features", b"not-wave"),
        ("--calibrate", bytes(832 * 18 - 1)),
        ("--calibrate", bytes(832 * 18 + 1)),
        ("--score", b"\x00\x01x"),
        ("--score", b"\xff\xff" + bytes(200000)),
    ],
)
def test_new_private_pipe_modes_reject_malformed_or_excess_input(probe_exe, mode, body):
    result = subprocess.run(
        [str(probe_exe), mode, "-"], input=body, capture_output=True, timeout=20
    )
    assert result.returncode == 2 and result.stdout == b""
    assert result.stderr.strip() == b"OFFLINE_WAKE_PROBE_REJECTED"


def test_fixture_diagnostics_expose_distance_but_not_biometric_feature(probe_exe):
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "pc_mic_wake_probe.py"),
            "--probe-exe",
            str(probe_exe),
            "--profile",
            str(PROFILE),
            "--fixture",
            str(FIXTURE / "evaluation" / "evaluation_wake_01.wav"),
            "--diagnostics",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "UNVERIFIED_MATCH" and data["wake_detected"] is True
    assert data["match"]["distance_q8"] < data["match"]["limit_q8"]
    assert data["processing_ms"] >= 0 and data["python_traced_peak_bytes"] > 0
    assert "features" not in data and str(PROFILE) not in result.stdout


def test_score_distinguishes_valid_no_feature_audio_from_malformed_wave(probe_exe):
    profile = PROFILE.read_bytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(bytes(48000))
    result = subprocess.run(
        [str(probe_exe), "--score", "-"],
        input=len(profile).to_bytes(2, "big") + profile + out.getvalue(),
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0 and json.loads(result.stdout) == {
        "accepted": False,
        "distance_q8": None,
        "limit_q8": 1003,
    }


def test_diagnostics_only_adds_fields_for_valid_pcm_below_feature_floor(probe_exe, tmp_path):
    wav = tmp_path / "synthetic-digital-silence.wav"
    with wave.open(str(wav), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(bytes(48000))
    statuses = []
    for extra in [[], ["--diagnostics"]]:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "pc_mic_wake_probe.py"),
                "--probe-exe",
                str(probe_exe),
                "--profile",
                str(PROFILE),
                "--fixture",
                str(wav),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        statuses.append(json.loads(result.stdout)["status"])
    assert statuses == ["UNVERIFIED_NO_MATCH", "UNVERIFIED_NO_MATCH"]
