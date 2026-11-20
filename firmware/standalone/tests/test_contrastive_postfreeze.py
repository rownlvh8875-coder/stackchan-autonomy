"""Reproducible post-freeze Heami test; no live voice, network, hardware."""

import hashlib
import shutil
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FRESH = ROOT / "fixtures" / "korean_heami_contrastive_postfreeze_20261120"
MANIFEST = FRESH / "post-freeze.wake-corpus.json"


def test_new_synthetic_holdout_and_exact_sha256(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_fresh_frozen_heami import load_new_holdout

    digest_lines = (FRESH / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(digest_lines) == 17
    observed = set()
    for line in digest_lines:
        expected, filename = line.split("  ", maxsplit=1)
        assert len(expected) == 64
        assert filename not in observed
        assert not filename.startswith("/") and ".." not in Path(filename).parts
        observed.add(filename)
        item = FRESH / filename
        assert item.is_file() and not item.is_symlink()
        assert hashlib.sha256(item.read_bytes()).hexdigest() == expected
    wavs = sorted(FRESH.rglob("*.wav"))
    assert len(wavs) == 16
    assert "post-freeze.wake-corpus.json" in observed
    assert set(path.relative_to(FRESH).as_posix() for path in wavs).issubset(observed)

    for filename in wavs:
        with wave.open(str(filename), "rb") as source:
            assert (
                source.getnchannels(),
                source.getsampwidth(),
                source.getframerate(),
            ) == (1, 2, 24000)
            assert 2400 <= source.getnframes() <= 72000

    entries = load_new_holdout(MANIFEST)
    assert len(entries) == 16
    assert sum(row["label"] == "wake" for row in entries) == 4
    assert sum(row["label"] == "nonwake" for row in entries) == 12
    assert not list(FRESH.rglob("*.exe"))
    assert not list(FRESH.rglob("*.pdb"))


def test_cpp_report_contract_is_strict(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_contrastive_postfreeze import (
        EXPERIMENTAL_NEGATIVE_MARGIN,
        FROZEN_HEAD,
        PostFreezeRejected,
        _read_counts,
    )

    assert FROZEN_HEAD == "a59e7beaa3df74da5f45a646140f4b8e6336f6ae"
    assert EXPERIMENTAL_NEGATIVE_MARGIN == 2.0
    output = (
        "UNVERIFIED_CALIBRATION_ONLY_CONTRASTIVE_WAKE\n"
        "calibration_negative_count=18\n"
        "positive_accepted=3/4\n"
        "negative_accepted=1/12\n"
    )
    parsed = _read_counts(output, contrastive=True)
    assert parsed["wake"] == {"accepted": 3, "total": 4}
    assert parsed["nonwake"] == {"accepted": 1, "total": 12}
    with pytest.raises(PostFreezeRejected):
        _read_counts(output.replace("3/4", "3/3"), contrastive=True)
    with pytest.raises(PostFreezeRejected):
        _read_counts(output.replace("1/12", "13/12"), contrastive=True)


def test_real_cpp_same_voice_heldout_rejects_deployment(monkeypatch):
    if not shutil.which("g++"):
        pytest.skip("Linux C++20 g++ required; Windows runs static tests")
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_contrastive_postfreeze import compare

    result = compare(MANIFEST)
    assert result["status"] == "NEW_HEAMI_SAME_TTS_POST_FREEZE_COMPARISON"
    assert result["candidate_recommendation"] == "REJECT_HARDWARE_DEPLOYMENT"
    assert result["candidate_has_wake_detection_regression"]
    assert not result["candidate_reduced_any_false_accept_on_new_holdout"]
    assert not result["candidate_deployment_authorized"]
    assert not result["real_world_false_wake_rate_proven"]
    assert not result["human_voice_and_room_diversity_proven"]

    assert set(result["results"]) == {
        "clean",
        "gain_half",
        "noise_20db",
        "noise_10db",
        "noise_5db",
        "noise_0db",
        "echo_80ms",
        "echo_160ms",
    }
    for variants in result["results"].values():
        original = variants["positive_profile_only"]
        filtered = variants["contrastive_filter"]
        if "status" in original or "status" in filtered:
            assert original == {"status": "fail_closed_no_counts"}
            assert filtered == {"status": "fail_closed_no_counts"}
            continue
        assert filtered["wake"]["accepted"] <= original["wake"]["accepted"]
        assert filtered["nonwake"]["accepted"] <= original["nonwake"]["accepted"]
        assert filtered["wake"]["total"] == original["wake"]["total"] == 4
        assert filtered["nonwake"]["total"] == original["nonwake"]["total"] == 12
