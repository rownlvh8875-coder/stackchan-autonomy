"""Local Windows SAPI Korean TTS plan and optional private integration test.

No media generation in regular CI: set STACKCHAN_RUN_LOCAL_SAPI=1 explicitly.
"""

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.fixture
def sapi(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools" / "synthesize_korean_wake_sapi.py"
    spec = importlib.util.spec_from_file_location("synthesize_korean_wake_sapi", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_24_korean_tts_samples_use_genuine_korean_script_and_no_mislabeled_wake(sapi):
    plan = sapi.voice_plan()
    assert len(plan) == 24
    groups = {(stage, label): [] for stage, label, _, _ in plan}
    for stage, label, phrase, rate in plan:
        assert -10 <= rate <= 10
        assert stage in {"enrollment", "calibration", "evaluation"}
        assert label in {"wake", "nonwake"}
        assert isinstance(phrase, str) and phrase
        if label == "wake":
            assert phrase == "조수"
        else:
            assert phrase != "조수"
        groups[(stage, label)].append((phrase, rate))
    assert [
        len(groups[stage, label])
        for stage, label in (
            ("enrollment", "wake"),
            ("calibration", "wake"),
            ("calibration", "nonwake"),
            ("evaluation", "wake"),
            ("evaluation", "nonwake"),
        )
    ] == [1, 5, 10, 2, 6]
    assert len(set(groups["calibration", "wake"])) == 5
    assert len(set(groups["evaluation", "wake"])) == 2
    assert ("calibration", "nonwake", "조수야", 0) in plan
    assert ("evaluation", "nonwake", "조수야", -2) in plan


def test_legacy_phrase_is_explicit_only_and_not_default(sapi):
    old = sapi.voice_plan("조수야")
    assert all(phrase == "조수야" for _, label, phrase, _ in old if label == "wake")
    assert ("calibration", "nonwake", "조수", 0) in old
    with pytest.raises(ValueError, match="unsupported_wake_phrase"):
        sapi.voice_plan("조수님")


@pytest.mark.skipif(os.name != "nt", reason="SAPI engine is Windows-only")
def test_existing_private_folder_not_overwritten(sapi, tmp_path):
    target = tmp_path / "already-present"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("KEEP")
    with pytest.raises(ValueError, match="output_directory_already_exists"):
        sapi.generate(target)
    assert sentinel.read_text() == "KEEP"


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("STACKCHAN_RUN_LOCAL_SAPI") != "1",
    reason="requires explicit local SAPI test opt-in, never automatic CI TTS",
)
def test_opt_in_local_heami_tts_generates_24_valid_wavs(sapi, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(sapi.__file__).parent))
    from wake_corpus_audit import inspect_corpus

    target = tmp_path / "private-sapi"
    report = sapi.generate(target)
    assert report["status"] == "LOCAL_SYNTHETIC_KOREAN_TTS_GENERATED"
    assert report["voice"] == "Microsoft Heami Desktop"
    assert report["wake_phrase"] == "조수"
    assert report["synthetic_only"] and not report["network_or_paid_api_used"]
    assert not report["robot_or_microphone_accessed"]
    manifest = target / "synthetic-sapi.wake-corpus.json"
    checked = inspect_corpus(manifest)
    assert checked["status"] == "CORPUS_STRUCTURALLY_SCREENED"
    assert checked["total_files"] == 24
    assert not checked["screening_warnings"]
    assert len(list(target.rglob("*.wav"))) == 24
    assert not list(target.glob("sapi-raw-*"))
