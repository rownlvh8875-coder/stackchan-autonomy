"""Deterministic host-only tiny CNN training on known Heami dev clips.

Only 6 wake and 26 nonwake source training/calibration clips. No existing
evaluation WAV is read, no private voice data uploaded, no K151 API or device.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluate_synthetic_robustness import _write_pcm_wav, perturb
from train_synthetic_linear_kws import (
    CONDITIONS_TRAIN,
    EXPECTED_AUG,
    SyntheticTrainRejected,
    training_sources,
)

MODEL_SIZE = 1423


def _run_native(path: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyntheticTrainRejected("tiny_cnn_native_execution_failed") from exc
    if completed.returncode != 0 or len(completed.stdout) > 4096:
        raise SyntheticTrainRejected("tiny_cnn_native_rejected")
    return completed.stdout


def train(trainer: Path, evaluator: Path, output: Path) -> dict:
    if not trainer.is_file() or not evaluator.is_file():
        raise SyntheticTrainRejected("native_cpp_tools_unavailable")
    checkout = Path(__file__).resolve().parents[3]
    resolved = output.resolve()
    if resolved.is_relative_to(checkout) or output.exists() or output.is_symlink():
        raise SyntheticTrainRejected("unsafe_existing_or_repository_destination")
    source = training_sources()
    with tempfile.TemporaryDirectory(prefix="stackchan-conv-kws-train-") as tmp:
        folder = Path(tmp)
        records = []
        totals = {"wake": 0, "nonwake": 0}
        for index, item in enumerate(source):
            label = item["label"]
            for condition in CONDITIONS_TRAIN:
                filename = folder / f"train_{index:03}_{condition}.wav"
                _write_pcm_wav(filename, perturb(item["pcm"], condition, item["id"]))
                records.append(f"{'W' if label == 'wake' else 'N'}\t{filename}")
                totals[label] += 1
        if totals != EXPECTED_AUG:
            raise SyntheticTrainRejected("incorrect_synthetic_training_groups")
        manifest = folder / "training.tsv"
        manifest.write_text("\n".join(records) + "\n", encoding="utf-8")
        candidate = folder / "candidate.skwc"
        trained = _run_native(trainer, str(manifest), str(candidate))
        if not trained.startswith("UNVERIFIED_SYNTHETIC_TINY_CNN_TRAINING\n"):
            raise SyntheticTrainRejected("unexpected_cnn_training_response")
        raw = candidate.read_bytes()
        if len(raw) != MODEL_SIZE or raw[:5] != b"SKWC1":
            raise SyntheticTrainRejected("unexpected_cnn_model_bytes")
        evaluated = _run_native(evaluator, str(candidate), str(manifest))
        if not evaluated.startswith("UNVERIFIED_TINY_CNN_MFCC_EVALUATION\n"):
            raise SyntheticTrainRejected("unexpected_cnn_evaluation_response")
        with output.open("xb") as destination:
            destination.write(raw)
    return {
        "status": "FROZEN_SYNTHETIC_TINY_CNN_TRAINING",
        "classifier": "tiny trainable temporal CNN 8 filters x 3 frames; 4-region average ReLU",
        "model_bytes": MODEL_SIZE,
        "model_sha256": hashlib.sha256(raw).hexdigest(),
        "training_base_wake_clips": 6,
        "training_base_nonwake_clips": 26,
        "training_augmented_wake_examples": totals["wake"],
        "training_augmented_nonwake_examples": totals["nonwake"],
        "training_data_not_independent": True,
        "training_example_acceptance": evaluated.splitlines()[1:3],
        "previous_evaluation_wavs_opened": False,
        "real_human_accuracy_proven": False,
        "device_install_authorized": False,
        "robot_or_paid_api_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trainer", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = train(arguments.trainer, arguments.evaluator, arguments.output)
        code = 0
    except (OSError, ValueError, SyntheticTrainRejected) as exc:
        report = {
            "status": "REJECTED_SYNTHETIC_TINY_CNN_TRAINING",
            "reason": exc.args[0] if isinstance(exc, SyntheticTrainRejected) else "input_invalid",
            "device_install_authorized": False,
            "robot_or_paid_api_accessed": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
