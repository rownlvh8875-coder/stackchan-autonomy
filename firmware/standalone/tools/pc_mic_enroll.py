"""Explicit PC-only private '조수' enrollment. RAM-only audio; no robot or API.

3 enrollment +5/10 calibration, then frozen-profile 5/10 fresh evaluation,
plus3 quiet windows. Only a passing session may save a new ignored SWK1 file.
"""

import argparse
import hashlib
import json
import math
import os
import stat
import time
import tracemalloc
from pathlib import Path

from pc_mic_audio import AudioError, select_microphone
from pc_mic_profile import EnrollmentError, helper, score_wav, validate_profile
from pc_mic_wake_probe import ProbeError, record_laptop_mic, safe_file

ROOT = Path(__file__).resolve().parents[3]
NEGATIVES = [
    "조수야",
    "조수님",
    "조수석",
    "주스",
    "주소",
    "조용히 해줘",
    "오늘 날씨 알려줘",
    "안녕 친구",
    "잘 자",
    "내일 다시 보자",
]


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise EnrollmentError("invalid_arguments")


def run_session(probe, baseline, capture):
    """capture(stage,label,index,prompt) supplies one newly captured WAV and quality.

    Labels are operator supplied. Hash/feature duplicates are rejected, but no
    algorithm here proves which words were spoken or that voices are independent.
    """
    validate_profile(baseline)
    seen_audio, seen_features, training, durations = set(), set(), [], []
    personal = None

    def counts():
        return dict(
            wake_accepted=0,
            wake_total=0,
            nonwake_accepted=0,
            nonwake_total=0,
            quiet_accepted=0,
            quiet_windows=0,
        )

    personal_counts, baseline_counts = counts(), counts()
    for stage, label, count in [
        ("enrollment", "wake", 3),
        ("calibration", "wake", 5),
        ("calibration", "nonwake", 10),
        ("evaluation", "wake", 5),
        ("evaluation", "nonwake", 10),
        ("evaluation", "quiet", 3),
    ]:
        if stage == "evaluation" and personal is None:
            personal = validate_profile(helper(probe, "--calibrate", b"".join(training)))
            training.clear()  # Evaluation never feeds calibration or a second threshold attempt.
        for index in range(count):
            if label == "wake":
                style = ["보통 속도", "조금 빠르게", "조금 느리게", "작은 목소리", "약1m 거리"][
                    index % 5
                ]
                prompt = f"조수 ({style})"
            else:
                prompt = NEGATIVES[index] if label == "nonwake" else "말하지 않고 생활 소음만"
            wav, diagnostic = capture(stage, label, index, prompt)
            issues = diagnostic.get("quality_issues", [])
            quiet = label == "quiet" and wav is None and issues == ["NO_SPEECH_ACTIVITY"]
            if not quiet and (wav is None or issues):
                raise EnrollmentError("capture_quality_rejected")
            started = time.perf_counter()
            if wav is not None:
                digest = hashlib.sha256(wav).digest()
                if digest in seen_audio:
                    raise EnrollmentError("duplicate_recording")
                seen_audio.add(digest)
                feature = helper(probe, "--features", wav)
                if len(feature) != 832:
                    raise EnrollmentError("invalid_feature")
                fingerprint = hashlib.sha256(feature).digest()
                if fingerprint in seen_features:
                    raise EnrollmentError("duplicate_feature")
                seen_features.add(fingerprint)
                if stage != "evaluation":
                    training.append(feature)
                    durations.append((time.perf_counter() - started) * 1000)
                    continue
            for model, stats in [(personal, personal_counts), (baseline, baseline_counts)]:
                accepted = bool(wav is not None and score_wav(probe, model, wav)["accepted"])
                if label == "quiet":
                    stats["quiet_windows"] += 1
                    stats["quiet_accepted"] += int(accepted)
                else:
                    stats[label + "_total"] += 1
                    stats[label + "_accepted"] += int(accepted)
            durations.append((time.perf_counter() - started) * 1000)
    passed = (
        personal_counts["wake_accepted"] == 5
        and personal_counts["nonwake_accepted"] == 0
        and personal_counts["quiet_accepted"] == 0
    )
    report = {
        "status": "PC_SESSION_PASSED_NOT_K151_VALIDATION"
        if passed
        else "PC_SESSION_FAILED_NEW_EVALUATION_REQUIRED",
        "wake_phrase": "조수",
        "personal": personal_counts,
        "baseline": baseline_counts,
        "threshold_frozen_before_evaluation": True,
        "evaluation_reused_for_training": False,
        "processing_ms_max": round(max(durations), 3),
        "processing_ms_mean": round(sum(durations) / len(durations), 3),
        "raw_audio_saved": False,
        "audio_features_saved": False,
        "network_or_paid_api_used": False,
        "k151_microphone_verified": False,
        "k151_firmware_modified": False,
        "independence_and_spoken_labels_operator_supplied": True,
    }
    return (personal if passed else None), report


def output_target(path, root=ROOT):
    path = Path(path).absolute()
    private = Path(root).resolve() / ".local"
    # Reject symlinks/junctions, including parents, and avoid existing file overwrite.
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            metadata = part.lstat()
            if part.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise EnrollmentError("private_output_required")
    if not path.resolve().is_relative_to(private) or path.suffix != ".swk1" or path.exists():
        raise EnrollmentError("new_private_output_required")
    return path


def save_private_profile(path, profile, root=ROOT):
    validate_profile(profile)
    path = output_target(path, root)
    created = False
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        output_target(path, root)
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR
        )
        created = True
        with os.fdopen(descriptor, "wb") as target:
            if target.write(profile) != len(profile):
                raise OSError("short_write")
            target.flush()
            os.fsync(target.fileno())
    except OSError as exc:
        if created:
            try:
                path.unlink()
            except OSError:
                raise EnrollmentError("private_profile_cleanup_failed_do_not_use_file") from None
        raise EnrollmentError("private_profile_write_failed") from exc


def main(argv=None):
    parser = PrivateParser(description=__doc__)
    parser.add_argument(
        "--enroll", action="store_true", help="explicitly start prompted local recordings"
    )
    parser.add_argument("--probe-exe", type=Path)
    parser.add_argument(
        "--baseline-profile",
        type=Path,
        default=ROOT / "firmware/standalone/fixtures/korean_josu_sapi_20261120/josu-20261120.swk1",
    )
    parser.add_argument("--output", type=Path)
    device = parser.add_mutually_exclusive_group()
    device.add_argument("--device", type=int)
    device.add_argument("--choose-device", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.5)
    try:
        args = parser.parse_args(argv)
        if not args.enroll or args.probe_exe is None or args.output is None:
            raise EnrollmentError("explicit_enrollment_and_private_output_required")
        if args.device is None and not args.choose_device:
            raise EnrollmentError("explicit_input_device_required")
        if not math.isfinite(args.seconds) or not 0.2 <= args.seconds <= 3:
            raise EnrollmentError("invalid_record_duration")
        output_target(args.output)
        probe = safe_file(args.probe_exe, 5_000_000)
        baseline = validate_profile(safe_file(args.baseline_profile, 2507).read_bytes())
        device, identity = select_microphone(args.device, args.choose_device)
        print("각 녹음에서 Enter를 누른 뒤 RECORDING 표시 후 말하세요. Ctrl+C로 취소합니다.")
        print(
            "원본 음성/특징은 파일에 저장하지 않습니다. 통과한 개인 SWK1만 지정한 .local 파일에 저장합니다."
        )

        def capture(stage, label, index, prompt):
            input(f"{stage} {label} {index + 1}: {prompt} — Enter: ")
            diagnostics = {}
            wav, _ = record_laptop_mic(
                device, args.seconds, expected_identity=identity, diagnostics=diagnostics
            )
            print(
                json.dumps(
                    {"stage": stage, "trial": index + 1, "quality": diagnostics}, ensure_ascii=False
                )
            )
            return wav, diagnostics

        tracemalloc.start()
        try:
            profile, report = run_session(probe, baseline, capture)
            _, report["python_traced_peak_bytes"] = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        report["profile_saved"] = False
        if profile is not None:
            save_private_profile(args.output, profile)
            report["profile_saved"] = True
        print(json.dumps(report, ensure_ascii=False))
        return 0 if profile else 3
    except KeyboardInterrupt:
        print(json.dumps({"status": "PC_ENROLLMENT_CANCELLED", "raw_audio_saved": False}))
        return 130
    except (EnrollmentError, AudioError, ProbeError, OSError, ValueError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, (EnrollmentError, AudioError, ProbeError))
            else "local_io_unavailable"
        )
        print(
            json.dumps(
                {
                    "status": "PC_ENROLLMENT_REJECTED",
                    "reason": reason,
                    "raw_audio_saved": False,
                    "network_or_paid_api_used": False,
                    "k151_hardware_accessed": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
