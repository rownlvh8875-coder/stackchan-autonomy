"""One-time frozen synthetic holdout verification (NEVER real K151 proof)."""

import hashlib
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FRESH = ROOT / "fixtures" / "korean_heami_fresh_holdout_20261120"
PREVIOUS = ROOT / "fixtures" / "korean_heami_sapi_20261120"
FROZEN = FRESH / "robust_trim_aug_frozen.swk1"
BASELINE = PREVIOUS / "heami-korean-offline-zig.swk1"


def test_sealed_heami_files_match_sha256_and_roles(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_fresh_frozen_heami import (
        FROZEN_CANDIDATE_SHA256,
        load_new_holdout,
    )
    from scfg_offline import validate_profile

    rows = (FRESH / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 18
    discovered = set()
    for row in rows:
        expected, filename = row.split("  ", maxsplit=1)
        assert len(expected) == 64
        assert filename not in discovered
        discovered.add(filename)
        path = FRESH / filename
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert len(tuple(FRESH.rglob("*.wav"))) == 16
    assert "robust_trim_aug_frozen.swk1" in discovered
    assert "fresh-evaluation.wake-corpus.json" in discovered
    assert len(discovered) == 18
    assert validate_profile(FROZEN.read_bytes()) == 3
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_CANDIDATE_SHA256
    clips = load_new_holdout(FRESH / "fresh-evaluation.wake-corpus.json")
    assert len(clips) == 16
    assert sum(item["label"] == "wake" for item in clips) == 4
    assert sum(item["label"] == "nonwake" for item in clips) == 12
    assert not list(FRESH.rglob("*.exe"))
    assert not list(FRESH.rglob("*.pdb"))


def test_real_cpp_matchers_on_postfreeze_tts_is_not_deployment_evidence(monkeypatch):
    if shutil.which("g++") is None:
        pytest.skip("Linux C++20 g++ required; no network/compiler install")
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_fresh_frozen_heami import compare_frozen

    report = compare_frozen(FRESH / "fresh-evaluation.wake-corpus.json", BASELINE, FROZEN)
    assert report["status"] == "NEW_SAME_TTS_HELDOUT_FROZEN_RECIPE_COMPARISON"
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
    assert report["candidate_has_observed_false_accepts"]
    assert not report["candidate_recommended_for_deployment"]
    assert not report["real_korean_accuracy_proven"]
    assert not report["install_authorized"]
    assert not report["human_speaker_independence_proven"]
    for condition, variants in report["conditions"].items():
        for label in ("baseline", "trim_augmented"):
            candidate = variants[label]
            if "status" in candidate:
                assert candidate["status"] == "fail_closed_no_group_counts"
                continue
            assert candidate["wake"]["total"] == 4, (condition, label)
            assert candidate["nonwake"]["total"] == 12, (condition, label)
