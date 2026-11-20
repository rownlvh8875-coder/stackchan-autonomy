"""One-shot frozen CNN Heami comparison; no live robot/microphone/paid API."""

import hashlib
import shutil
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
FRESH = BASE / "fixtures" / "korean_heami_conv_postfreeze_20261120"
MANIFEST = FRESH / "cnn-postfreeze.wake-corpus.json"


def test_postfreeze_16_clips_are_unchanged_and_evaluation_only(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_conv_postfreeze import CONV_SHA256, FROZEN_COMMIT
    from evaluate_fresh_frozen_heami import load_new_holdout

    assert FROZEN_COMMIT == "92a3796620d6a87aa651d914e19e5aca5af390c9"
    assert CONV_SHA256 == ("3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5")
    fingerprints = (FRESH / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(fingerprints) == 17
    found = set()
    for line in fingerprints:
        expected, path = line.split("  ", maxsplit=1)
        assert len(expected) == 64 and path not in found
        assert not path.startswith("/") and ".." not in Path(path).parts
        found.add(path)
        content = FRESH / path
        assert content.is_file() and not content.is_symlink()
        assert hashlib.sha256(content.read_bytes()).hexdigest() == expected
    assert "cnn-postfreeze.wake-corpus.json" in found
    recordings = sorted(FRESH.rglob("*.wav"))
    assert len(recordings) == 16
    for path in recordings:
        assert path.relative_to(FRESH).as_posix() in found
        with wave.open(str(path), "rb") as stream:
            assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (
                1,
                2,
                24000,
            )
            assert 2400 <= stream.getnframes() <= 72000
    labeled = load_new_holdout(MANIFEST)
    assert len(labeled) == 16
    assert sum(row["label"] == "wake" for row in labeled) == 4
    assert sum(row["label"] == "nonwake" for row in labeled) == 12
    assert not list(FRESH.rglob("*.exe"))


def test_comparison_result_strict_count_parser(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_conv_postfreeze import CnnHoldoutRejected, parse_counts

    response = (
        "UNVERIFIED_TINY_CNN_MFCC_EVALUATION\npositive_accepted=4/4\nnegative_accepted=3/12\n"
    )
    assert parse_counts(response, "tiny_cnn") == {
        "wake": {"accepted": 4, "total": 4},
        "nonwake": {"accepted": 3, "total": 12},
    }
    with pytest.raises(CnnHoldoutRejected):
        parse_counts(response.replace("4/4", "4/3"), "tiny_cnn")
    with pytest.raises(CnnHoldoutRejected):
        parse_counts(response.replace("3/12", "13/12"), "tiny_cnn")
    with pytest.raises(CnnHoldoutRejected):
        parse_counts(response.replace("negative_accepted", "other"), "tiny_cnn")


def test_real_linux_cpp_postfreeze_cnn_is_not_deployable(monkeypatch):
    if not shutil.which("g++"):
        pytest.skip("Linux CI C++20 compiler required")
    monkeypatch.syspath_prepend(str(TOOLS))
    from evaluate_conv_postfreeze import evaluate

    result = evaluate(MANIFEST)
    assert result["status"] == "POST_FREEZE_SAME_HEAMI_CNN_COMPARISON"
    assert result["frozen_model_commit"] == ("92a3796620d6a87aa651d914e19e5aca5af390c9")
    assert result["cnn_has_observed_false_accepts"]
    assert not result["models_retrained_using_this_holdout"]
    assert not result["approved_for_device_installation"]
    assert not result["independent_human_speakers_tested"]
    assert not result["real_world_wake_accuracy_proven"]
    assert not result["physical_K151_audio_or_GPIO_accessed"]
    assert set(result["conditions"]) == {
        "clean",
        "gain_half",
        "noise_20db",
        "noise_10db",
        "noise_5db",
        "noise_0db",
        "echo_80ms",
        "echo_160ms",
    }
    clean = result["conditions"]["clean"]["tiny_cnn"]
    assert clean["wake"]["accepted"] == 4
    assert clean["nonwake"]["accepted"] >= 1  # veto for device deployment
    for variants in result["conditions"].values():
        for name in ("original_dtw", "augmented_dtw", "linear", "tiny_cnn"):
            counted = variants[name]
            if "status" in counted:
                assert counted == {"status": "fail_closed_no_group_counts"}
                continue
            assert counted["wake"]["total"] == 4
            assert counted["nonwake"]["total"] == 12
