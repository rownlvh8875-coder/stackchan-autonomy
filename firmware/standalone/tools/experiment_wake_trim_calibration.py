"""Training/calibration-only robust wake experiments, NO evaluation samples read.

Experiment compares fixed feature trimming and augmented templates against the
published C++ MFCC/DTW implementation. It only reads enrollment/calibration
WAVs. It intentionally NEVER opens evaluation WAVs, avoiding test leakage.
Results are development diagnostics, not recognition accuracy.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from evaluate_synthetic_robustness import CONDITIONS, _write_pcm_wav, perturb
from wake_corpus_audit import (
    MAX_WAV_BYTES,
    _decode_canonical_wav,
    _read_bounded,
    _safe_relative_file,
)

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
CORPUS = ROOT / "fixtures" / "korean_heami_sapi_20261120"
SOURCE = CORPUS / "synthetic-sapi.wake-corpus.json"


def _compile(source: str, target: Path, *, trim: bool) -> None:
    native = shutil.which("g++")
    if native:
        prefix = [native]
    else:
        cached = shutil.which("uvx")
        if not cached:
            raise RuntimeError("native_or_cached_offline_compiler_missing")
        prefix = [cached, "--offline", "--from", "ziglang==0.15.2", "python-zig", "c++"]
    args = [
        *prefix,
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-I",
        str(ROOT / "core"),
    ]
    if trim:
        args.append("-DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1")
    args.extend([str(TOOLS / source), "-o", str(target)])
    result = subprocess.run(args, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError("offline_host_compile_failed")


def _run(binary: Path, args: list[str]) -> str:
    run = subprocess.run(
        [str(binary), *args], capture_output=True, text=True, timeout=100, check=False
    )
    if run.returncode:
        raise RuntimeError("offline_mfcc_stage_rejected")
    return run.stdout


def _counts(stdout: str) -> dict:
    lines = stdout.splitlines()
    if not lines or lines[0] != "UNVERIFIED_USER_LABELED_WAKE_EVALUATION":
        raise RuntimeError("invalid_matcher_output")
    result = {}
    for label in ("positive", "negative"):
        candidates = [x for x in lines if x.startswith(label + "_accepted=")]
        if len(candidates) != 1:
            raise RuntimeError("invalid_matcher_counts")
        accepted, total = map(int, candidates[0].split("=")[1].split("/"))
        result[label] = {"accepted": accepted, "total": total}
    return result


def calibration_only_records() -> dict:
    # This function deliberately does NOT read evaluation WAVs.
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    grouped = {"enroll": [], "positive": [], "negative": []}
    for item in manifest["samples"]:
        if item["stage"] == "evaluation":
            continue
        path = _safe_relative_file(CORPUS, item["file"])
        pcm = _decode_canonical_wav(_read_bounded(path, MAX_WAV_BYTES))
        key = (
            "enroll"
            if item["stage"] == "enrollment"
            else ("positive" if item["label"] == "wake" else "negative")
        )
        grouped[key].append({"id": item["id"], "pcm": pcm})
    if tuple(map(len, grouped.values())) != (1, 5, 10):
        raise RuntimeError("unexpected_training_split")
    return grouped


def frozen_dev_gates_pass(candidate: dict) -> bool:
    """Only calibration rows, NEVER an evaluation count or WAV."""
    if candidate.get("status") != "training_only_diagnostics":
        return False
    for condition in ("clean", "gain_half", "noise_20db", "noise_10db", "echo_80ms"):
        observed = candidate["conditions"].get(condition, {})
        if observed.get("positive") != {"accepted": 5, "total": 5} or observed.get("negative") != {
            "accepted": 0,
            "total": 10,
        }:
            return False
    return True


def inspect_training_only(freeze_profile: Path | None = None) -> dict:
    dataset = calibration_only_records()
    with tempfile.TemporaryDirectory(prefix="stackchan-robust-dev-") as temp:
        folder = Path(temp)
        tools = {}
        for tag, trim in (("baseline", False), ("trim", True)):
            enroll = folder / ("enroll_" + tag + ".exe")
            eval_bin = folder / ("eval_" + tag + ".exe")
            _compile("wake_wav_enroll.cpp", enroll, trim=trim)
            _compile("wake_wav_eval.cpp", eval_bin, trim=trim)
            tools[tag] = (enroll, eval_bin)

        training_files = {}
        for key in ("enroll", "positive", "negative"):
            training_files[key] = []
            for item in dataset[key]:
                name = folder / f"{item['id']}.wav"
                _write_pcm_wav(name, item["pcm"])
                training_files[key].append(name)

        profiles = {}
        for candidate, tooltag, extra in (
            ("baseline", "baseline", ()),
            ("trim", "trim", ()),
            ("trim_augmented", "trim", ("noise_20db", "echo_80ms")),
        ):
            samples = list(training_files["enroll"])
            for condition in extra:
                name = folder / f"template_{condition}.wav"
                _write_pcm_wav(
                    name,
                    perturb(dataset["enroll"][0]["pcm"], condition, "enrollment_wake_01"),
                )
                samples.append(name)
            cmd = []
            for path in samples:
                cmd.extend(["--template", str(path)])
            for path in training_files["positive"]:
                cmd.extend(["--holdout", str(path)])
            for path in training_files["negative"]:
                cmd.extend(["--negative", str(path)])
            output = folder / (candidate + ".swk1")
            cmd.extend(["--output", str(output)])
            try:
                _run(tools[tooltag][0], cmd)
                profiles[candidate] = (output, tools[tooltag][1])
            except RuntimeError:
                profiles[candidate] = None

        results = {}
        for candidate, info in profiles.items():
            if info is None:
                results[candidate] = {"status": "calibration_rejected"}
                continue
            profile, eval_bin = info
            scenarios = {}
            for condition in CONDITIONS:
                cmd = [str(profile)]
                for key, flag in (("positive", "--positive"), ("negative", "--negative")):
                    for item in dataset[key]:
                        path = folder / f"{candidate}_{condition}_{item['id']}.wav"
                        _write_pcm_wav(path, perturb(item["pcm"], condition, item["id"]))
                        cmd.extend([flag, str(path)])
                try:
                    scenarios[condition] = _counts(_run(eval_bin, cmd))
                except RuntimeError:
                    scenarios[condition] = {"status": "matcher_rejected"}
            results[candidate] = {
                "status": "training_only_diagnostics",
                "profile_bytes": profile.stat().st_size,
                "conditions": scenarios,
            }
        frozen = False
        fingerprint = None
        if freeze_profile is not None:
            # Do not freeze a candidate that did not pass the declared
            # DEVELOPMENT conditions with zero negative accepts. This never
            # looks at the published evaluation recordings.
            candidate = results.get("trim_augmented", {})
            if not frozen_dev_gates_pass(candidate):
                raise RuntimeError("candidate_did_not_pass_development_gates")
            repo = ROOT.parents[1]
            target = freeze_profile.resolve()
            if target.exists() or target.is_symlink() or (target == repo or repo in target.parents):
                raise RuntimeError("unsafe_or_existing_freeze_destination")
            source_bytes = profiles["trim_augmented"][0].read_bytes()
            with freeze_profile.open("xb") as file:
                file.write(source_bytes)
            fingerprint = hashlib.sha256(source_bytes).hexdigest()
            frozen = True
        return {
            "status": "SYNTHETIC_CALIBRATION_ONLY_EXPERIMENT",
            "source": "same Microsoft Heami TTS voice",
            "enrollment_clips": 1,
            "calibration_wake_clips": 5,
            "calibration_nonwake_clips": 10,
            "evaluation_wavs_opened": False,
            "independent_speakers_tested": False,
            "actual_korean_accuracy_proven": False,
            "device_install_authorized": False,
            "candidates": results,
            "profile_frozen_from_calibration_only": frozen,
            "frozen_profile_sha256": fingerprint,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze-profile", type=Path, help="exclusive private SWK1 file outside source checkout"
    )
    args = parser.parse_args()
    try:
        report = inspect_training_only(args.freeze_profile)
        code = 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        report = {
            "status": "ROBUST_DEV_REJECTED",
            "evaluation_wavs_opened": False,
            "device_install_authorized": False,
        }
        code = 2
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
