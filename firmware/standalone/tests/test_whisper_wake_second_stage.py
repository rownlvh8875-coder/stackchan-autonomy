"""Fail-closed tests of pinned local Whisper tiny as a second-stage wake gate.

CI requires no model installation and never downloads model/audio. Real CPU
ASR smoke tests are conducted separately on an authorized PC with pinned
model weights. The samples in these fixtures are all synthetic Heami TTS.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MANIFEST = (
    ROOT / "fixtures" / "korean_heami_conv_postfreeze_20261120" / "cnn-postfreeze.wake-corpus.json"
)
PROFILE = ROOT / "fixtures" / "korean_heami_fresh_holdout_20261120" / "robust_trim_aug_frozen.swk1"


@pytest.fixture
def whisper_module(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    source = TOOLS / "whisper_wake_second_stage.py"
    spec = importlib.util.spec_from_file_location(source.stem, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_whisper_model_and_decoding_rules(whisper_module):
    mod = whisper_module
    assert mod.MODEL_REPOSITORY == "Systran/faster-whisper-tiny"
    assert mod.MODEL_REVISION == "d90ca5fe260221311c53c58e660288d3deb8d356"
    assert mod.MODEL_WEIGHTS_SHA256 == (
        "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1"
    )
    assert mod.ASR_BEAM_SIZE == 5
    assert mod.ASR_CPU_THREADS == 4
    assert mod.ASR_MAX_NEW_TOKENS == 32
    assert mod.exact_wake_transcript("조수")
    assert mod.exact_wake_transcript("조 수!")
    assert not mod.exact_wake_transcript("조수야")
    assert not mod.exact_wake_transcript("조수영")
    assert not mod.exact_wake_transcript("조수야 안녕")
    assert not mod.exact_wake_transcript("")


def test_model_missing_corrupted_or_misnamed_fails_closed(whisper_module, tmp_path):
    model = tmp_path / whisper_module.MODEL_DIRECTORY_NAME
    model.mkdir()
    assert not whisper_module.verified_local_model(model)
    (model / "model.bin").write_bytes(b"not-model")
    (model / "config.json").write_text("{}")
    (model / "tokenizer.json").write_text("{}")
    assert not whisper_module.verified_local_model(model)
    with pytest.raises(whisper_module.OfflineWhisperRejected):
        whisper_module.load_pinned_whisper_model(model)
    model2 = tmp_path / "untrusted-unpinned-model"
    model2.mkdir()
    assert not whisper_module.verified_local_model(model2)


def test_second_stage_only_runs_on_stage1_acceptance(whisper_module, monkeypatch, tmp_path):
    mod = whisper_module
    monkeypatch.setattr(mod, "load_pinned_whisper_model", lambda _: object())

    # Four wake files and one near-phrase are admitted to stage 2.
    stage1_admit = {
        "cnn_eval_01.wav",
        "cnn_eval_02.wav",
        "cnn_eval_03.wav",
        "cnn_eval_04.wav",
        "cnn_eval_05.wav",
    }
    executed_first = []
    executed_second = []

    def fake_probe(_binary, _profile, path):
        executed_first.append(path.name)
        return path.name in stage1_admit

    transcripts = iter(["조수야", "조수야", "조세형", "", "조영수"])

    def fake_asr(_model, pcm):
        assert isinstance(pcm, bytes) and pcm
        executed_second.append(len(pcm))
        return next(transcripts)

    monkeypatch.setattr(mod, "stage1_probe", fake_probe)
    monkeypatch.setattr(mod, "transcript_from_whisper", fake_asr)
    result = mod.evaluate_whisper_stage2(
        MANIFEST,
        tmp_path / "fake-probe",
        PROFILE,
        tmp_path / "fake-unverified-model",
        wake_phrase="조수야",
    )
    assert len(executed_first) == 16
    assert len(executed_second) == 5
    assert result["stage1_accepted"] == {"wake": 4, "nonwake": 1}
    assert result["two_stage_accepted"] == {"wake": 2, "nonwake": 0}
    assert result["stage2_asr_invocations"] == 5
    assert not result["device_install_authorized"]
    assert not result["runtime_network_or_paid_api_used"]
    assert not result["real_speaker_independence_proven"]


def test_asr_failure_is_not_a_wake_accept(whisper_module, monkeypatch, tmp_path):
    mod = whisper_module
    monkeypatch.setattr(mod, "load_pinned_whisper_model", lambda _: object())
    monkeypatch.setattr(mod, "stage1_probe", lambda *_: True)

    def fail_closed(*_args):
        raise mod.OfflineWhisperRejected("offline_whisper_inference_failed")

    monkeypatch.setattr(mod, "transcript_from_whisper", fail_closed)
    with pytest.raises(mod.OfflineWhisperRejected, match="inference_failed"):
        mod.evaluate_whisper_stage2(
            MANIFEST, tmp_path / "fake-stage1", PROFILE, tmp_path / "fake-whisper-model"
        )


def test_no_firmware_integration_and_model_not_committed(whisper_module):
    hold = (ROOT / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "whisper_wake_second_stage" not in hold
    assert "faster_whisper" not in hold
    assert "faster-whisper-tiny" not in hold
    assert "CTranslate2" not in hold
    assert not list(ROOT.rglob("model.bin"))
    assert not list(ROOT.rglob("vosk-model-small-ko-0.22"))
