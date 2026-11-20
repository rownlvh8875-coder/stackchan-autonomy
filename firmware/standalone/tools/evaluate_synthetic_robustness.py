"""Deterministic synthetic robustness probes against the real C++ wake matcher.

Original Korean TTS clips can be public test fixtures, but perturbed audio is
generated in a private temp folder, never transmitted, persisted or enrolled.
The same base utterances recur across conditions: NOT independent observations.
"""

import argparse
import array
import hashlib
import json
import math
import random
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from wake_corpus_audit import (
    MAX_MANIFEST_BYTES,
    MAX_WAV_BYTES,
    _decode_canonical_wav,
    _object_without_duplicate_keys,
    _read_bounded,
    _safe_relative_file,
)

CONDITIONS = (
    "clean",
    "gain_half",
    "noise_20db",
    "noise_10db",
    "noise_5db",
    "noise_0db",
    "echo_80ms",
    "echo_160ms",
)
DEFAULT_COUNTS = {"wake": 2, "nonwake": 6}
MAX_EVAL_SECONDS = 120


class RobustnessError(ValueError):
    """Fixed public reason only, no user files or private data in exceptions."""


def _samples(pcm: bytes) -> list[int]:
    result = array.array("h")
    result.frombytes(pcm)
    if sys.byteorder != "little":
        result.byteswap()
    return result.tolist()


def _clip(value: float) -> int:
    return max(-32768, min(32767, round(value)))


def perturb(pcm: bytes, condition: str, sample_id: str) -> bytes:
    """Transform the same exact PCM samples, never a real microphone recording."""
    if condition not in CONDITIONS:
        raise RobustnessError("unknown_perturbation")
    original = _samples(pcm)
    if condition == "clean":
        return pcm
    if condition == "gain_half":
        out = [_clip(value * 0.5) for value in original]
    elif condition.startswith("noise_"):
        snr = int(condition.split("_")[1].removesuffix("db"))
        rms = math.sqrt(sum(value * value for value in original) / len(original))
        if rms == 0:
            raise RobustnessError("silence_cannot_be_perturbed")
        sigma = rms / (10 ** (snr / 20))
        seed = int.from_bytes(
            hashlib.sha256(f"{condition}:{sample_id}".encode()).digest()[:8], "little"
        )
        rng = random.Random(seed)
        out = [_clip(value + rng.gauss(0, sigma)) for value in original]
    else:
        delay_ms, coefficient = (80, 0.35) if condition == "echo_80ms" else (160, 0.55)
        delay = 24 * delay_ms  # 24 kHz, fixed-length single reflection
        out = [
            _clip(
                (value + coefficient * (original[i - delay] if i >= delay else 0))
                / (1 + coefficient)
            )
            for i, value in enumerate(original)
        ]
    values = array.array("h", out)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def load_public_evaluation(fixture: Path) -> list[dict]:
    if fixture.is_symlink() or not fixture.is_dir():
        raise RobustnessError("fixture_directory_unavailable")
    manifest = fixture / "synthetic-sapi.wake-corpus.json"
    try:
        doc = json.loads(
            _read_bounded(manifest, MAX_MANIFEST_BYTES).decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        if not isinstance(doc, dict) or set(doc) != {"schema", "samples"}:
            raise RobustnessError("fixture_manifest_invalid")
        if doc["schema"] != "stackchan-private-wake-corpus-v1":
            raise RobustnessError("fixture_manifest_invalid")
        trials = []
        for item in doc["samples"]:
            if item["stage"] != "evaluation":
                continue
            if item["label"] not in DEFAULT_COUNTS:
                raise RobustnessError("fixture_label_invalid")
            filename = _safe_relative_file(fixture, item["file"])
            raw = _read_bounded(filename, MAX_WAV_BYTES)
            pcm = _decode_canonical_wav(raw)
            trials.append({"id": item["id"], "label": item["label"], "pcm": pcm})
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
        raise RobustnessError("fixture_unavailable_or_invalid") from exc
    if len(trials) != sum(DEFAULT_COUNTS.values()) or any(
        sum(t["label"] == name for t in trials) != total for name, total in DEFAULT_COUNTS.items()
    ):
        raise RobustnessError("fixture_evaluation_split_invalid")
    return trials


def _write_pcm_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(pcm)


def _decode_answer(output: str) -> dict:
    lines = output.splitlines()
    if not lines or lines[0] != "UNVERIFIED_USER_LABELED_WAKE_EVALUATION":
        raise RobustnessError("unexpected_matcher_reply")
    results = {}
    for name in ("positive", "negative"):
        prefix = name + "_accepted="
        matched = [line for line in lines if line.startswith(prefix)]
        if len(matched) != 1:
            raise RobustnessError("missing_or_duplicate_matcher_count")
        fragment = matched[0].removeprefix(prefix).split("/")
        if len(fragment) != 2 or not all(x.isdecimal() for x in fragment):
            raise RobustnessError("matcher_count_invalid")
        accepted, total = map(int, fragment)
        if not 0 <= accepted <= total:
            raise RobustnessError("matcher_count_invalid")
        results[name] = {"accepted": accepted, "total": total}
    if (
        results["positive"]["total"] != DEFAULT_COUNTS["wake"]
        or results["negative"]["total"] != DEFAULT_COUNTS["nonwake"]
    ):
        raise RobustnessError("matcher_count_mismatch")
    return results


def evaluate(fixture: Path, profile: Path, evaluator: Path) -> dict:
    if not profile.is_file() or not evaluator.is_file():
        raise RobustnessError("profile_or_matcher_unavailable")
    trials = load_public_evaluation(fixture)
    by_condition = {}
    with tempfile.TemporaryDirectory(prefix="stackchan-sapi-perturb-") as private_dir:
        directory = Path(private_dir)
        for condition in CONDITIONS:
            args = [str(evaluator), str(profile)]
            for trial in trials:
                filename = directory / f"{condition}-{trial['id']}.wav"
                _write_pcm_wav(filename, perturb(trial["pcm"], condition, trial["id"]))
                args.extend(
                    [
                        "--positive" if trial["label"] == "wake" else "--negative",
                        str(filename),
                    ]
                )
            try:
                run = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=MAX_EVAL_SECONDS,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RobustnessError("matcher_execution_failed") from exc
            if run.returncode != 0:
                raise RobustnessError("matcher_rejected_perturbed_audio")
            by_condition[condition] = _decode_answer(run.stdout)

    return {
        "status": "SYNTHETIC_ROBUSTNESS_EXPERIMENT_NOT_HARDWARE_PROOF",
        "engine": "Microsoft Heami Desktop / Windows SAPI (source fixture)",
        "algorithm": "standalone C++ MFCC/DTW / fixed SWK1 threshold",
        "base_positive_clips": DEFAULT_COUNTS["wake"],
        "base_nonwake_clips": DEFAULT_COUNTS["nonwake"],
        "conditions": by_condition,
        "separate_speakers_or_rooms_tested": False,
        "independent_samples_across_conditions": False,
        "actual_korean_wake_accuracy_proven": False,
        "physical_robot_tested": False,
        "sound_files_uploaded_by_this_script": False,
        "network_or_paid_api_used": False,
        "device_install_authorized": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--evaluator", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.fixtures, args.profile, args.evaluator)
        status = 0
    except (RobustnessError, OSError) as exc:
        result = {
            "status": "REJECTED_SYNTHETIC_ROBUSTNESS_EXPERIMENT",
            "reason": exc.args[0] if isinstance(exc, RobustnessError) else "file_unavailable",
            "physical_robot_tested": False,
            "network_or_paid_api_used": False,
            "device_install_authorized": False,
        }
        status = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
