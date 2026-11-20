"""Fail-closed host-only Korean wake Vosk second-stage tests.

Never installs Vosk or a language model in CI; optional live offline model
smoke tests run only when explicitly requested on the owner's Windows PC.
"""

import array
import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
MANIFEST = (
    BASE / "fixtures" / "korean_heami_conv_postfreeze_20261120" / "cnn-postfreeze.wake-corpus.json"
)
PROFILE = BASE / "fixtures" / "korean_heami_fresh_holdout_20261120" / "robust_trim_aug_frozen.swk1"


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    script = TOOLS / "vosk_wake_second_stage.py"
    spec = importlib.util.spec_from_file_location("vosk_wake_second_stage", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("조수야", True),
        (" 조 수 야 ", True),
        ("조수야!", True),
        ("조수야?", True),
        ("조수야.", True),
        ("조수야 지금", False),
        ("조수아", False),
        ("조세형", False),
        ("조세 였다", False),
        ("조수님", False),
        ("주수야", False),
        ("소주야", False),
        ("안녕 조수야", False),
        ("조수야 안녕", False),
        ("", False),
        (None, False),
        (123, False),
        ("조수야" * 40, False),
    ],
)
def test_exact_korean_transcript_gate(verifier, text, expected):
    assert verifier.exact_wake_transcript(text) is expected


def test_resampler_and_canonical_audio_are_local_and_bounded(verifier, tmp_path):
    source = BASE / "fixtures" / "korean_heami_conv_postfreeze_20261120"
    wav = source / "evaluation" / "cnn_eval_01.wav"
    pcm = verifier.read_24k_mono_pcm16_wav(wav)
    converted = verifier.resample_24k_pcm16_to_16k(pcm)
    assert len(converted) == (len(pcm) // 2 * 2 // 3) * 2
    assert len(converted) > 0

    wave = array.array("h")
    wave.frombytes(converted)
    if sys.byteorder != "little":
        wave.byteswap()
    assert max(abs(value) for value in wave) > 50
    assert all(-32768 <= value <= 32767 for value in wave)
    with pytest.raises(verifier.OfflineVoskRejected):
        verifier.resample_24k_pcm16_to_16k(b"\x01")
    with pytest.raises(verifier.OfflineVoskRejected):
        verifier.resample_24k_pcm16_to_16k(b"\x00\x00" * 2200)
    with pytest.raises(verifier.OfflineVoskRejected):
        verifier.read_24k_mono_pcm16_wav(tmp_path / "missing.wav")


def test_stage1_requires_both_profile_and_valid_wav(verifier, tmp_path):
    with pytest.raises(verifier.OfflineVoskRejected):
        verifier.stage1_probe(tmp_path / "missing", PROFILE, tmp_path / "missing.wav")
    assert not verifier.valid_local_model_directory(tmp_path / "vosk-model-small-ko-0.22")


def test_fake_asr_called_only_after_stage1_accept(verifier, monkeypatch, tmp_path):
    model_dir = tmp_path / verifier.EXPECTED_KOREAN_MODEL_DIR
    for component in ("am", "conf", "graph", "ivector"):
        (model_dir / component).mkdir(parents=True, exist_ok=True)
    fake_vosk = types.SimpleNamespace(
        SetLogLevel=lambda _: None,
        Model=lambda _: object(),
    )
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)

    accepted = {"cnn_eval_01.wav", "cnn_eval_02.wav", "cnn_eval_05.wav"}
    calls = []

    def fake_stage1(_binary, _profile, wav):
        calls.append(Path(wav).name)
        return Path(wav).name in accepted

    transcript_results = iter(["조수야", "조세형", "조수야"])

    def fake_asr(_model, pcm):
        assert isinstance(pcm, bytes) and len(pcm) > 0
        return next(transcript_results)

    monkeypatch.setattr(verifier, "stage1_probe", fake_stage1)
    monkeypatch.setattr(verifier, "transcript_from_offline_vosk", fake_asr)
    answer = verifier.evaluate_cascade(MANIFEST, tmp_path / "fake-stage1", PROFILE, model_dir)
    assert len(calls) == 16
    assert answer["asr_invocations_after_stage1_accept"] == 3
    assert answer["stage1_accepted"] == {"wake": 2, "nonwake": 1}
    assert answer["two_stage_accepted"] == {"wake": 1, "nonwake": 1}
    assert not answer["device_install_authorized"]
    assert not answer["paid_api_or_network_used"]
    assert not answer["asr_confidence_calibrated"]


def test_cpp_single_probe_runs_offline_linux(tmp_path, verifier):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Host-only C++20 tests are exercised on Linux CI")
    binary = tmp_path / "stage1-probe"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1",
            "-I",
            str(BASE / "core"),
            str(TOOLS / "wake_stage1_probe.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=100,
    )
    positive = (
        BASE
        / "fixtures"
        / "korean_heami_conv_postfreeze_20261120"
        / "evaluation"
        / "cnn_eval_01.wav"
    )
    assert verifier.stage1_probe(binary, PROFILE, positive)
    nonwake = (
        BASE
        / "fixtures"
        / "korean_heami_conv_postfreeze_20261120"
        / "evaluation"
        / "cnn_eval_05.wav"
    )
    assert isinstance(verifier.stage1_probe(binary, PROFILE, nonwake), bool)


def test_approved_gate_never_bypasses_hardware_hold():
    hold = (BASE / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "wake_stage1_probe" not in hold
    assert "vosk_wake_second_stage" not in hold
    assert "vosk-model-small-ko-0.22" not in hold
