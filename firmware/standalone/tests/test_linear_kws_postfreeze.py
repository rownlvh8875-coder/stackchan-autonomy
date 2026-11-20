"""One-shot same-TTS holdout for the already frozen 847-byte linear KWS model."""

import hashlib
import shutil
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
FRESH = BASE / "fixtures" / "korean_heami_linear_postfreeze_20261120"
MANIFEST = FRESH / "linear-postfreeze.wake-corpus.json"


def test_postfreeze_synthetic_wavs_and_hashes_are_unmodified(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_fresh_frozen_heami import load_new_holdout
    from evaluate_linear_kws_postfreeze import PRE_EVAL_FREEZE_COMMIT

    assert PRE_EVAL_FREEZE_COMMIT == "80e280cf17717e4e2eb8a34fe71f99dce7bd6f4e"
    rows = (FRESH / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 17
    found = set()
    for line in rows:
        expected, file = line.split("  ", maxsplit=1)
        assert len(expected) == 64 and file not in found
        assert not file.startswith("/") and ".." not in Path(file).parts
        found.add(file)
        target = FRESH / file
        assert target.is_file() and not target.is_symlink()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    assert "linear-postfreeze.wake-corpus.json" in found
    recordings = sorted(FRESH.rglob("*.wav"))
    assert len(recordings) == 16
    assert all(path.relative_to(FRESH).as_posix() in found for path in recordings)
    for recording in recordings:
        with wave.open(str(recording), "rb") as media:
            assert (media.getnchannels(), media.getsampwidth(), media.getframerate()) == (
                1,
                2,
                24000,
            )
            assert 2400 <= media.getnframes() <= 72000
    labeled = load_new_holdout(MANIFEST)
    assert len(labeled) == 16
    assert sum(row["label"] == "wake" for row in labeled) == 4
    assert sum(row["label"] == "nonwake" for row in labeled) == 12
    assert not list(FRESH.rglob("*.exe"))
    assert not list(FRESH.rglob("*.pdb"))


def test_linear_response_requires_complete_denominators(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_linear_kws_postfreeze import (
        PostFreezeLinearRejected,
        _counts,
    )

    raw = "UNVERIFIED_LINEAR_MFCC_KWS_EVALUATION\npositive_accepted=4/4\nnegative_accepted=2/12\n"
    assert _counts(raw, linear=True) == {
        "wake": {"accepted": 4, "total": 4},
        "nonwake": {"accepted": 2, "total": 12},
    }
    with pytest.raises(PostFreezeLinearRejected):
        _counts(raw.replace("4/4", "4/3"), linear=True)
    with pytest.raises(PostFreezeLinearRejected):
        _counts(raw.replace("2/12", "13/12"), linear=True)
    with pytest.raises(PostFreezeLinearRejected):
        _counts(raw.replace("negative_accepted", "unknown"), linear=True)


def test_host_cpp_same_heami_holdout_is_not_deployable(monkeypatch):
    if not shutil.which("g++"):
        pytest.skip("Linux CI supplies native g++; Windows has static checks")
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_linear_kws_postfreeze import evaluate

    report = evaluate(MANIFEST)
    assert report["status"] == "NEW_HEAMI_POST_FREEZE_LINEAR_MFCC_COMPARISON"
    assert report["holdout_wake"] == 4 and report["holdout_nonwake"] == 12
    assert not report["classifier_tuned_on_this_holdout"]
    assert not report["real_speech_accuracy_proven"]
    assert not report["real_false_wakes_per_hour_measured"]
    assert not report["device_install_authorized"]
    assert not report["physical_robot_accessed"]
    assert not report["paid_api_or_network_used"]
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
    clean = report["conditions"]["clean"]
    assert clean["linear"]["nonwake"]["accepted"] >= 1
    for result in report["conditions"].values():
        for method in ("original_dtw", "augmented_dtw", "linear"):
            measurement = result[method]
            if "status" in measurement:
                assert measurement == {"status": "fail_closed_no_group_counts"}
                continue
            assert measurement["wake"]["total"] == 4
            assert measurement["nonwake"]["total"] == 12
