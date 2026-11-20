"""One-shot host-only comparison after tiny CNN freeze, NO model tuning.

All four methods consume identical fresh same-Heami TTS WAVs; the frozen
CNN model is checked by SHA256. No ESP32, microphone, network or paid API.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluate_fresh_frozen_heami import load_new_holdout
from evaluate_synthetic_robustness import CONDITIONS, _write_pcm_wav, perturb
from experiment_wake_trim_calibration import _compile

BASE = Path(__file__).resolve().parents[1]
CONV = BASE / "fixtures" / "korean_heami_conv_kws_20261120" / "conv-kws-frozen.skwc"
LINEAR = BASE / "fixtures" / "korean_heami_linear_kws_20261120" / "linear-kws-training-frozen.skwl"
ORIGINAL = BASE / "fixtures" / "korean_heami_sapi_20261120" / "heami-korean-offline-zig.swk1"
AUGMENTED = (
    BASE / "fixtures" / "korean_heami_fresh_holdout_20261120" / "robust_trim_aug_frozen.swk1"
)
CONV_SHA256 = "3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5"
LINEAR_SHA256 = "4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788"
AUGMENTED_SHA256 = "b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec"
FROZEN_COMMIT = "92a3796620d6a87aa651d914e19e5aca5af390c9"


class CnnHoldoutRejected(ValueError):
    """Fixed non-sensitive error description only."""


def parse_counts(message: str, label: str) -> dict:
    headers = {
        "original_dtw": "UNVERIFIED_USER_LABELED_WAKE_EVALUATION",
        "augmented_dtw": "UNVERIFIED_USER_LABELED_WAKE_EVALUATION",
        "linear": "UNVERIFIED_LINEAR_MFCC_KWS_EVALUATION",
        "tiny_cnn": "UNVERIFIED_TINY_CNN_MFCC_EVALUATION",
    }
    lines = message.splitlines()
    if not lines or lines[0] != headers[label]:
        raise CnnHoldoutRejected("unexpected_cpp_evaluation_header")
    scores = {}
    for kind, name, required in (
        ("wake", "positive_accepted=", 4),
        ("nonwake", "negative_accepted=", 12),
    ):
        selected = [line for line in lines if line.startswith(name)]
        if len(selected) != 1:
            raise CnnHoldoutRejected("missing_cpp_evaluation_count")
        numbers = selected[0].removeprefix(name).split("/")
        if len(numbers) != 2 or not all(item.isascii() and item.isdecimal() for item in numbers):
            raise CnnHoldoutRejected("invalid_cpp_evaluation_count")
        accepted, total = map(int, numbers)
        if not 0 <= accepted <= total or total != required:
            raise CnnHoldoutRejected("wrong_cpp_evaluation_denominator")
        scores[kind] = {"accepted": accepted, "total": total}
    return scores


def evaluate(manifest: Path) -> dict:
    for file, expected, size in (
        (CONV, CONV_SHA256, 1423),
        (LINEAR, LINEAR_SHA256, 847),
        (AUGMENTED, AUGMENTED_SHA256, 2507),
    ):
        raw = file.read_bytes()
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
            raise CnnHoldoutRejected("frozen_model_or_profile_changed")
    clips = load_new_holdout(manifest)
    if len(clips) != 16:
        raise CnnHoldoutRejected("unexpected_heldout_size")

    with tempfile.TemporaryDirectory(prefix="stackchan-cnn-after-freeze-") as tmp:
        folder = Path(tmp)
        binaries = {
            key: folder / (key + ".exe")
            for key in ("original_dtw", "augmented_dtw", "linear", "tiny_cnn")
        }
        _compile("wake_wav_eval.cpp", binaries["original_dtw"], trim=False)
        _compile("wake_wav_eval.cpp", binaries["augmented_dtw"], trim=True)
        _compile("wake_linear_eval.cpp", binaries["linear"], trim=False)
        _compile("wake_conv_eval.cpp", binaries["tiny_cnn"], trim=False)

        output = {}
        for condition in CONDITIONS:
            dtw_args = []
            tsv_lines = []
            for clip in clips:
                file = folder / f"{condition}_{clip['id']}.wav"
                _write_pcm_wav(file, perturb(clip["pcm"], condition, clip["id"]))
                dtw_args.extend(
                    [
                        "--positive" if clip["label"] == "wake" else "--negative",
                        str(file),
                    ]
                )
                tsv_lines.append(f"{'W' if clip['label'] == 'wake' else 'N'}\t{file}")
            evaluation_tsv = folder / "evaluation.tsv"
            evaluation_tsv.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
            commands = (
                ("original_dtw", [str(binaries["original_dtw"]), str(ORIGINAL), *dtw_args]),
                ("augmented_dtw", [str(binaries["augmented_dtw"]), str(AUGMENTED), *dtw_args]),
                ("linear", [str(binaries["linear"]), str(LINEAR), str(evaluation_tsv)]),
                ("tiny_cnn", [str(binaries["tiny_cnn"]), str(CONV), str(evaluation_tsv)]),
            )
            condition_results = {}
            for name, command in commands:
                try:
                    run = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise CnnHoldoutRejected("native_cpp_evaluation_failed") from exc
                condition_results[name] = (
                    parse_counts(run.stdout, name)
                    if run.returncode == 0
                    else {"status": "fail_closed_no_group_counts"}
                )
            output[condition] = condition_results

    return {
        "status": "POST_FREEZE_SAME_HEAMI_CNN_COMPARISON",
        "frozen_model_commit": FROZEN_COMMIT,
        "conv_model_sha256": CONV_SHA256,
        "four_synthetic_wake_clips": True,
        "twelve_synthetic_nonwake_clips": True,
        "conditions": output,
        "cnn_has_observed_false_accepts": any(
            item["tiny_cnn"].get("nonwake", {}).get("accepted", 0) > 0 for item in output.values()
        ),
        "approved_for_device_installation": False,
        "models_retrained_using_this_holdout": False,
        "independent_human_speakers_tested": False,
        "real_world_wake_accuracy_proven": False,
        "physical_K151_audio_or_GPIO_accessed": False,
        "network_or_paid_api_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(args.holdout_manifest)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report = {
            "status": "REJECTED_SAME_HEAMI_CNN_HOLDOUT",
            "reason": exc.args[0]
            if isinstance(exc, CnnHoldoutRejected)
            else "local_evaluation_error",
            "approved_for_device_installation": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
