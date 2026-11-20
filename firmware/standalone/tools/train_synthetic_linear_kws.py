"""Offline deterministic synthetic Heami training for a tiny linear MFCC KWS.

Explicitly consumes ONLY formerly published enrollment/calibration recordings.
It never reads any "evaluation" role or path; none of the previously exposed
evaluation clips may be presented as unbiased fresh validation. Synthetic
perturbations are repetitions of SAME base clips, not independent samples.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluate_synthetic_robustness import _write_pcm_wav, perturb
from wake_corpus_audit import (
    MAX_MANIFEST_BYTES,
    MAX_WAV_BYTES,
    _decode_canonical_wav,
    _object_without_duplicate_keys,
    _read_bounded,
    _safe_relative_file,
)

BASE = Path(__file__).resolve().parents[1]
ORIGINAL = BASE / "fixtures" / "korean_heami_sapi_20261120"
HARDNEG = BASE / "fixtures" / "korean_heami_hardneg_20261120"
CONDITIONS_TRAIN = ("clean", "gain_half", "noise_20db", "noise_10db", "echo_80ms")
EXPECTED_BASE = {"wake": 6, "nonwake": 26}
EXPECTED_AUG = {"wake": 30, "nonwake": 130}


class SyntheticTrainRejected(ValueError):
    """Fixed machine-readable errors only. Never echo private filenames."""


def training_sources() -> list[dict]:
    original = json.loads(
        _read_bounded(ORIGINAL / "synthetic-sapi.wake-corpus.json", MAX_MANIFEST_BYTES).decode(
            "utf-8"
        ),
        object_pairs_hook=_object_without_duplicate_keys,
    )
    additional = json.loads(
        _read_bounded(HARDNEG / "hard-negative-calibration.json", MAX_MANIFEST_BYTES).decode(
            "utf-8"
        ),
        object_pairs_hook=_object_without_duplicate_keys,
    )
    if original["schema"] != "stackchan-private-wake-corpus-v1" or additional["kind"] != (
        "synthetic_heami_nonwake_calibration_only_v1"
    ):
        raise SyntheticTrainRejected("unexpected_training_corpus")
    results = []
    for record in original["samples"]:
        if record["stage"] == "evaluation":
            continue  # Never inspect evaluation audio; role must be explicit.
        if record["stage"] not in ("calibration", "enrollment"):
            raise SyntheticTrainRejected("unexpected_training_role")
        path = _safe_relative_file(ORIGINAL, record["file"])
        pcm = _decode_canonical_wav(_read_bounded(path, MAX_WAV_BYTES))
        results.append(
            {
                "label": record["label"],
                "pcm": pcm,
                "id": record["id"],
            }
        )
    for record in additional["labels"]:
        if record["role"] != "calibration" or record["label"] != "nonwake":
            raise SyntheticTrainRejected("hardneg_not_calibration_only")
        path = _safe_relative_file(HARDNEG, record["file"])
        pcm = _decode_canonical_wav(_read_bounded(path, MAX_WAV_BYTES))
        results.append(
            {
                "label": "nonwake",
                "pcm": pcm,
                "id": path.stem,
            }
        )
    counts = {label: sum(row["label"] == label for row in results) for label in ("wake", "nonwake")}
    if counts != EXPECTED_BASE or len({row["id"] for row in results}) != len(results):
        raise SyntheticTrainRejected("incorrect_training_split")
    return results


def _call_cli(program: Path, *args: str) -> str:
    try:
        run = subprocess.run(
            [str(program), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyntheticTrainRejected("native_kws_program_unavailable") from exc
    if run.returncode != 0 or len(run.stdout) > 10000:
        raise SyntheticTrainRejected("native_kws_program_rejected")
    return run.stdout


def fit_synthetic(trainer: Path, evaluator: Path, output: Path) -> dict:
    if not trainer.is_file() or not evaluator.is_file():
        raise SyntheticTrainRejected("native_executable_missing")
    repo = BASE.parents[1]
    target = output.resolve()
    if target.is_relative_to(repo) or target.exists() or output.is_symlink():
        raise SyntheticTrainRejected("unsafe_or_existing_model_destination")

    examples = training_sources()
    with tempfile.TemporaryDirectory(prefix="stackchan-linear-train-") as temp:
        root = Path(temp)
        lines = []
        groups = {"wake": [], "nonwake": []}
        for index, row in enumerate(examples):
            for condition in CONDITIONS_TRAIN:
                filename = root / f"train_{index:02}_{condition}.wav"
                _write_pcm_wav(filename, perturb(row["pcm"], condition, row["id"]))
                lines.append(f"{'W' if row['label'] == 'wake' else 'N'}\t{filename}")
                groups[row["label"]].append(filename)
        train_manifest = root / "training.tsv"
        train_manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        intermediate = root / "model.skwl"
        training_response = _call_cli(trainer, str(train_manifest), str(intermediate))
        if not training_response.startswith("UNVERIFIED_SYNTHETIC_LINEAR_KWS_TRAINING\n"):
            raise SyntheticTrainRejected("unexpected_training_response")
        count = {label: len(files) for label, files in groups.items()}
        if count != EXPECTED_AUG:
            raise SyntheticTrainRejected("unexpected_augmentation_count")
        binary = intermediate.read_bytes()
        if len(binary) != 847 or binary[:5] != b"SKWL1":
            raise SyntheticTrainRejected("invalid_synthetic_model_format")

        evaluation_manifest = root / "development.tsv"
        evaluation_manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        observed = _call_cli(evaluator, str(intermediate), str(evaluation_manifest))
        if not observed.startswith("UNVERIFIED_LINEAR_MFCC_KWS_EVALUATION\n"):
            raise SyntheticTrainRejected("unexpected_development_evaluation")
        with output.open("xb") as target_file:
            target_file.write(binary)
    return {
        "status": "FROZEN_SYNTHETIC_LINEAR_MFCC_TRAINING",
        "architecture": "time-pooled 16x13 MFCC logistic-linear, NOT phoneme ASR",
        "model_bytes": len(binary),
        "model_sha256": hashlib.sha256(binary).hexdigest(),
        "source_wake_utterances": EXPECTED_BASE["wake"],
        "source_nonwake_utterances": EXPECTED_BASE["nonwake"],
        "augmented_wake_examples": EXPECTED_AUG["wake"],
        "augmented_nonwake_examples": EXPECTED_AUG["nonwake"],
        "augmented_samples_are_independent": False,
        "development_results_on_training_samples": observed.splitlines()[1:3],
        "previous_evaluation_wavs_opened": False,
        "human_accuracy_proven": False,
        "robot_or_paid_api_accessed": False,
        "install_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trainer", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = fit_synthetic(args.trainer, args.evaluator, args.output)
        code = 0
    except (SyntheticTrainRejected, OSError, ValueError) as exc:
        data = {
            "status": "REJECTED_LINEAR_SYNTHETIC_TRAINING",
            "reason": exc.args[0] if isinstance(exc, SyntheticTrainRejected) else "input_invalid",
            "install_authorized": False,
            "robot_or_paid_api_accessed": False,
        }
        code = 2
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
