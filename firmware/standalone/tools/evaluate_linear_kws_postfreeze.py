"""Compare frozen linear MFCC classifier with fixed DTW profiles on NEW TTS.

No threshold tuning, training, enrollment, network or K151 actions. The new
holdout is SAME Heami synthetic voice, NOT human independence or accuracy.
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
MODEL = BASE / "fixtures" / "korean_heami_linear_kws_20261120" / "linear-kws-training-frozen.skwl"
ORIGINAL = BASE / "fixtures" / "korean_heami_sapi_20261120" / "heami-korean-offline-zig.swk1"
AUGMENTED = (
    BASE / "fixtures" / "korean_heami_fresh_holdout_20261120" / "robust_trim_aug_frozen.swk1"
)
LINEAR_SHA256 = "4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788"
AUGMENTED_SHA256 = "b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec"
PRE_EVAL_FREEZE_COMMIT = "80e280cf17717e4e2eb8a34fe71f99dce7bd6f4e"


class PostFreezeLinearRejected(ValueError):
    """Never echo raw voice material, private paths, profiles, or user metadata."""


def _counts(stdout: str, *, linear: bool) -> dict:
    tag = (
        "UNVERIFIED_LINEAR_MFCC_KWS_EVALUATION"
        if linear
        else "UNVERIFIED_USER_LABELED_WAKE_EVALUATION"
    )
    lines = stdout.splitlines()
    if not lines or lines[0] != tag:
        raise PostFreezeLinearRejected("invalid_classifier_response")
    result = {}
    for key, marker, required in (
        ("wake", "positive_accepted=", 4),
        ("nonwake", "negative_accepted=", 12),
    ):
        selected = [line for line in lines if line.startswith(marker)]
        if len(selected) != 1:
            raise PostFreezeLinearRejected("missing_or_duplicate_response")
        values = selected[0].removeprefix(marker).split("/")
        if len(values) != 2 or not all(item.isascii() and item.isdecimal() for item in values):
            raise PostFreezeLinearRejected("invalid_classification_counts")
        accepted, total = map(int, values)
        if not 0 <= accepted <= total or total != required:
            raise PostFreezeLinearRejected("wrong_result_denominator")
        result[key] = {"accepted": accepted, "total": total}
    return result


def evaluate(manifest: Path) -> dict:
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != LINEAR_SHA256:
        raise PostFreezeLinearRejected("frozen_linear_model_changed")
    if len(MODEL.read_bytes()) != 847:
        raise PostFreezeLinearRejected("frozen_linear_model_size_changed")
    if hashlib.sha256(AUGMENTED.read_bytes()).hexdigest() != AUGMENTED_SHA256:
        raise PostFreezeLinearRejected("frozen_dtw_profile_changed")
    clips = load_new_holdout(manifest)  # 4 wake + 12 nonwake; no old holdout read.

    with tempfile.TemporaryDirectory(prefix="linear-heldout-host-") as temp:
        home = Path(temp)
        binaries = {
            "original_dtw": home / "old_dtw.exe",
            "augmented_dtw": home / "augmented_dtw.exe",
            "linear": home / "linear.exe",
        }
        _compile("wake_wav_eval.cpp", binaries["original_dtw"], trim=False)
        _compile("wake_wav_eval.cpp", binaries["augmented_dtw"], trim=True)
        _compile("wake_linear_eval.cpp", binaries["linear"], trim=False)

        report = {}
        for condition in CONDITIONS:
            dtw_inputs = []
            linear_inputs = []
            for clip in clips:
                filename = home / f"{condition}_{clip['id']}.wav"
                _write_pcm_wav(filename, perturb(clip["pcm"], condition, clip["id"]))
                dtw_inputs.extend(
                    ["--positive" if clip["label"] == "wake" else "--negative", str(filename)]
                )
                linear_inputs.append(f"{'W' if clip['label'] == 'wake' else 'N'}\t{filename}")

            evaluation_tsv = home / "evaluation.tsv"
            evaluation_tsv.write_text("\n".join(linear_inputs) + "\n", encoding="utf-8")
            cases = (
                ("original_dtw", [str(binaries["original_dtw"]), str(ORIGINAL), *dtw_inputs]),
                ("augmented_dtw", [str(binaries["augmented_dtw"]), str(AUGMENTED), *dtw_inputs]),
                ("linear", [str(binaries["linear"]), str(MODEL), str(evaluation_tsv)]),
            )
            result = {}
            for label, command in cases:
                try:
                    execution = subprocess.run(
                        command, capture_output=True, text=True, check=False, timeout=120
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise PostFreezeLinearRejected("native_classifier_execution_failed") from exc
                if execution.returncode != 0:
                    result[label] = {"status": "fail_closed_no_group_counts"}
                else:
                    result[label] = _counts(execution.stdout, linear=label == "linear")
            report[condition] = result

    return {
        "status": "NEW_HEAMI_POST_FREEZE_LINEAR_MFCC_COMPARISON",
        "model_frozen_commit": PRE_EVAL_FREEZE_COMMIT,
        "linear_sha256": LINEAR_SHA256,
        "holdout_wake": 4,
        "holdout_nonwake": 12,
        "conditions": report,
        "classifier_tuned_on_this_holdout": False,
        "separate_human_voices_tested": False,
        "real_speech_accuracy_proven": False,
        "real_false_wakes_per_hour_measured": False,
        "physical_robot_accessed": False,
        "paid_api_or_network_used": False,
        "device_install_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.holdout_manifest)
        status = 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {
            "status": "REJECTED_NEW_LINEAR_KWS_HOLDOUT",
            "reason": exc.args[0]
            if isinstance(exc, PostFreezeLinearRejected)
            else "offline_evaluation_unavailable",
            "physical_robot_accessed": False,
            "device_install_authorized": False,
        }
        status = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
