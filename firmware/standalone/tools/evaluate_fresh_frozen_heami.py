"""One-shot comparison on NEW synthetic Heami holdouts (generated after freeze).

The development script never reads these files. This evaluator cannot change
the frozen SWK1 profile or train thresholds. Report is NOT human accuracy.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluate_synthetic_robustness import CONDITIONS, _write_pcm_wav, perturb
from experiment_wake_trim_calibration import _compile
from scfg_offline import validate_profile
from wake_corpus_audit import (
    MAX_MANIFEST_BYTES,
    MAX_WAV_BYTES,
    _decode_canonical_wav,
    _object_without_duplicate_keys,
    _read_bounded,
    _safe_relative_file,
)

FROZEN_CANDIDATE_SHA256 = "b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec"
EXPECTED_COUNTS = {"wake": 4, "nonwake": 12}


class HoldoutRejected(ValueError):
    """No user paths, raw audio, or secrets in error output."""


def load_new_holdout(manifest: Path) -> list[dict]:
    if manifest.is_symlink() or not manifest.name.endswith(".wake-corpus.json"):
        raise HoldoutRejected("unsafe_holdout_manifest")
    try:
        document = json.loads(
            _read_bounded(manifest, MAX_MANIFEST_BYTES).decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        if not isinstance(document, dict) or set(document) != {"schema", "samples"}:
            raise HoldoutRejected("invalid_holdout_manifest")
        if document["schema"] != "stackchan-private-wake-corpus-v1":
            raise HoldoutRejected("invalid_holdout_schema")
        clips = []
        digests = set()
        for sample in document["samples"]:
            if (
                not isinstance(sample, dict)
                or set(sample) != {"id", "stage", "label", "session", "file"}
                or sample["stage"] != "evaluation"
            ):
                raise HoldoutRejected("holdout_contains_training_role")
            if sample["label"] not in EXPECTED_COUNTS:
                raise HoldoutRejected("unexpected_holdout_label")
            path = _safe_relative_file(manifest.parent, sample["file"])
            pcm = _decode_canonical_wav(_read_bounded(path, MAX_WAV_BYTES))
            fingerprint = hashlib.sha256(pcm).digest()
            if fingerprint in digests:
                raise HoldoutRejected("duplicate_holdout_pcm")
            digests.add(fingerprint)
            clips.append({"id": sample["id"], "label": sample["label"], "pcm": pcm})
    except HoldoutRejected:
        raise
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
        raise HoldoutRejected("invalid_or_inaccessible_holdout") from exc
    for name, expected in EXPECTED_COUNTS.items():
        if sum(clip["label"] == name for clip in clips) != expected:
            raise HoldoutRejected("unexpected_holdout_counts")
    return clips


def _read_evaluation(response: str) -> dict:
    lines = response.splitlines()
    if not lines or lines[0] != "UNVERIFIED_USER_LABELED_WAKE_EVALUATION":
        raise HoldoutRejected("invalid_cpp_result")
    scores = {}
    for label, prefix in (("wake", "positive_accepted="), ("nonwake", "negative_accepted=")):
        rows = [line for line in lines if line.startswith(prefix)]
        if len(rows) != 1:
            raise HoldoutRejected("ambiguous_cpp_result")
        numbers = rows[0].removeprefix(prefix).split("/")
        if len(numbers) != 2 or not all(t.isascii() and t.isdecimal() for t in numbers):
            raise HoldoutRejected("malformed_cpp_result")
        accepted, total = map(int, numbers)
        if total != EXPECTED_COUNTS[label] or not 0 <= accepted <= total:
            raise HoldoutRejected("incorrect_cpp_counts")
        scores[label] = {"accepted": accepted, "total": total}
    return scores


def compare_frozen(manifest: Path, baseline_profile: Path, frozen_profile: Path) -> dict:
    if not baseline_profile.is_file() or not frozen_profile.is_file():
        raise HoldoutRejected("missing_profile")
    try:
        baseline = baseline_profile.read_bytes()
        candidate = frozen_profile.read_bytes()
        if validate_profile(baseline) != 1 or validate_profile(candidate) != 3:
            raise HoldoutRejected("unexpected_profile_template_count")
        if hashlib.sha256(candidate).hexdigest() != FROZEN_CANDIDATE_SHA256:
            raise HoldoutRejected("frozen_profile_hash_changed")
    except (ValueError, OSError) as exc:
        raise HoldoutRejected("bad_profile") from exc

    clips = load_new_holdout(manifest)
    with tempfile.TemporaryDirectory(prefix="stackchan-sealed-tts-") as temporary:
        temp = Path(temporary)
        binaries = {
            "baseline": temp / "baseline.exe",
            "trim_augmented": temp / "trim_augmented.exe",
        }
        _compile("wake_wav_eval.cpp", binaries["baseline"], trim=False)
        _compile("wake_wav_eval.cpp", binaries["trim_augmented"], trim=True)
        results = {}
        for condition in CONDITIONS:
            args = []
            for clip in clips:
                name = temp / f"{condition}_{clip['id']}.wav"
                _write_pcm_wav(name, perturb(clip["pcm"], condition, clip["id"]))
                args.extend(
                    [
                        "--positive" if clip["label"] == "wake" else "--negative",
                        str(name),
                    ]
                )
            per_variant = {}
            for tag, profile in (
                ("baseline", baseline_profile),
                ("trim_augmented", frozen_profile),
            ):
                try:
                    run = subprocess.run(
                        [str(binaries[tag]), str(profile), *args],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HoldoutRejected("cpp_evaluation_unavailable") from exc
                if run.returncode != 0:
                    per_variant[tag] = {"status": "fail_closed_no_group_counts"}
                else:
                    per_variant[tag] = _read_evaluation(run.stdout)
            results[condition] = per_variant

    return {
        "status": "NEW_SAME_TTS_HELDOUT_FROZEN_RECIPE_COMPARISON",
        "frozen_candidate_sha256": FROZEN_CANDIDATE_SHA256,
        "holdout_total": len(clips),
        "holdout_wake": EXPECTED_COUNTS["wake"],
        "holdout_nonwake": EXPECTED_COUNTS["nonwake"],
        "conditions": results,
        "candidate_has_observed_false_accepts": any(
            item["trim_augmented"].get("nonwake", {}).get("accepted", 0) > 0
            for item in results.values()
        ),
        "candidate_recommended_for_deployment": False,
        "frozen_recipe_tuned_on_this_holdout": False,
        "human_speaker_independence_proven": False,
        "real_korean_accuracy_proven": False,
        "hardware_k151_accessed": False,
        "network_or_paid_api_used": False,
        "install_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-manifest", required=True, type=Path)
    parser.add_argument("--baseline-profile", required=True, type=Path)
    parser.add_argument("--frozen-profile", required=True, type=Path)
    args = parser.parse_args()
    try:
        output = compare_frozen(args.holdout_manifest, args.baseline_profile, args.frozen_profile)
        code = 0
    except (HoldoutRejected, OSError, subprocess.TimeoutExpired) as exc:
        output = {
            "status": "SEALED_SAME_TTS_HOLDOUT_REJECTED",
            "reason": exc.args[0] if isinstance(exc, HoldoutRejected) else "local_execution_failed",
            "install_authorized": False,
        }
        code = 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
