"""One-shot comparison on NEW same-TTS holdout created AFTER a59e7be.

Both experimental variants use the same frozen 3-template SWK1. The veto
additionally compares 18 calibration-only negative features against each
probe. No tuning or threshold changes are made after seeing this holdout.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluate_fresh_frozen_heami import load_new_holdout
from evaluate_synthetic_robustness import CONDITIONS, _write_pcm_wav, perturb
from experiment_contrastive_calibration import (
    HARDNEG,
    OLD_PROFILE,
    _compile,
    calibration_only_records,
    private_hardneg,
)
from scfg_offline import validate_profile

FROZEN_HEAD = "a59e7beaa3df74da5f45a646140f4b8e6336f6ae"
FROZEN_POSITIVE_PROFILE_SHA256 = "b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec"
EXPERIMENTAL_NEGATIVE_MARGIN = 2.0


class PostFreezeRejected(ValueError):
    """Public fixed error names only: do not print file paths or raw audio."""


def _read_counts(stdout: str, *, contrastive: bool) -> dict:
    prefix = (
        "UNVERIFIED_CALIBRATION_ONLY_CONTRASTIVE_WAKE"
        if contrastive
        else "UNVERIFIED_USER_LABELED_WAKE_EVALUATION"
    )
    lines = stdout.splitlines()
    if not lines or lines[0] != prefix:
        raise PostFreezeRejected("unexpected_matching_response")
    result = {}
    for label, stem, total in (
        ("wake", "positive_accepted=", 4),
        ("nonwake", "negative_accepted=", 12),
    ):
        matching = [line for line in lines if line.startswith(stem)]
        if len(matching) != 1:
            raise PostFreezeRejected("missing_or_duplicate_group_results")
        fragment = matching[0].removeprefix(stem).split("/")
        if len(fragment) != 2 or not all(x.isascii() and x.isdecimal() for x in fragment):
            raise PostFreezeRejected("invalid_cpp_counts")
        accepted, observed_total = map(int, fragment)
        if not 0 <= accepted <= total or observed_total != total:
            raise PostFreezeRejected("count_denominator_mismatch")
        result[label] = {"accepted": accepted, "total": total}
    return result


def compare(manifest: Path, profile: Path = OLD_PROFILE) -> dict:
    if validate_profile(profile.read_bytes()) != 3:
        raise PostFreezeRejected("positive_profile_unexpected")
    if hashlib.sha256(profile.read_bytes()).hexdigest() != FROZEN_POSITIVE_PROFILE_SHA256:
        raise PostFreezeRejected("positive_profile_changed")
    holdout = load_new_holdout(manifest)
    if len(holdout) != 16:
        raise PostFreezeRejected("unexpected_synthetic_holdout_size")
    original_training = calibration_only_records()
    additional_bank, _ = private_hardneg(HARDNEG)
    bank = original_training["negative"] + additional_bank
    if len(bank) != 18:
        raise PostFreezeRejected("negative_bank_count_wrong")

    with tempfile.TemporaryDirectory(prefix="contrastive-postfreeze-") as temporary:
        home = Path(temporary)
        native = home / "baseline.exe"
        veto = home / "contrastive.exe"
        _compile("wake_wav_eval.cpp", native, trim=True)
        _compile("wake_contrastive_eval.cpp", veto, trim=True)
        bank_args = []
        for item in bank:
            filename = home / f"train_{item['id']}.wav"
            _write_pcm_wav(filename, item["pcm"])
            bank_args.extend(["--calibration-negative", str(filename)])

        results = {}
        for condition in CONDITIONS:
            probes = []
            for item in holdout:
                filename = home / f"{condition}_{item['id']}.wav"
                _write_pcm_wav(filename, perturb(item["pcm"], condition, item["id"]))
                probes.extend(
                    [
                        "--positive" if item["label"] == "wake" else "--negative",
                        str(filename),
                    ]
                )
            variants = {}
            for name, tool, extra in (
                ("positive_profile_only", native, []),
                ("contrastive_filter", veto, bank_args),
            ):
                try:
                    call = subprocess.run(
                        [str(tool), str(profile), *extra, *probes],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise PostFreezeRejected("cpp_evaluation_not_available") from exc
                if call.returncode != 0:
                    variants[name] = {"status": "fail_closed_no_counts"}
                else:
                    variants[name] = _read_counts(
                        call.stdout, contrastive=name == "contrastive_filter"
                    )
            results[condition] = variants

    available = [
        pair
        for pair in results.values()
        if "wake" in pair["positive_profile_only"] and "wake" in pair["contrastive_filter"]
    ]
    wake_regression = any(
        pair["contrastive_filter"]["wake"]["accepted"]
        < pair["positive_profile_only"]["wake"]["accepted"]
        for pair in available
    )
    any_false_accept_reduction = any(
        pair["contrastive_filter"]["nonwake"]["accepted"]
        < pair["positive_profile_only"]["nonwake"]["accepted"]
        for pair in available
    )
    return {
        "status": "NEW_HEAMI_SAME_TTS_POST_FREEZE_COMPARISON",
        "candidate_has_wake_detection_regression": wake_regression,
        "candidate_reduced_any_false_accept_on_new_holdout": any_false_accept_reduction,
        "candidate_recommendation": "REJECT_HARDWARE_DEPLOYMENT",
        "recipe_frozen_in_commit": FROZEN_HEAD,
        "negative_margin_ratio_frozen": EXPERIMENTAL_NEGATIVE_MARGIN,
        "training_negative_bank_count": len(bank),
        "holdout_wake": 4,
        "holdout_nonwake": 12,
        "results": results,
        "training_data_tuned_on_this_holdout": False,
        "human_voice_and_room_diversity_proven": False,
        "real_world_false_wake_rate_proven": False,
        "robot_or_microphone_accessed": False,
        "network_or_paid_api_used": False,
        "candidate_deployment_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-manifest", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        report = compare(arguments.holdout_manifest)
        code = 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report = {
            "status": "POST_FREEZE_SYNTHETIC_HOLDOUT_REJECTED",
            "reason": exc.args[0]
            if isinstance(exc, PostFreezeRejected)
            else "offline_comparison_failed",
            "candidate_deployment_authorized": False,
            "robot_or_microphone_accessed": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
