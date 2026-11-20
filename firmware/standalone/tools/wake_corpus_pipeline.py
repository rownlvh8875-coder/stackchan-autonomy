"""Private end-to-end wake corpus workflow; no robot, network or paid API.

Run audited WAV training/calibration with the existing C++20 MFCC/DTW tool and
evaluate ONLY the independently declared evaluation files. Refuse to publish a
profile if any step fails. This cannot prove labels or recordings are genuine.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from scfg_offline import ProtocolError, validate_profile
from wake_corpus_audit import (
    MAX_MANIFEST_BYTES,
    MAX_WAV_BYTES,
    CorpusError,
    _object_without_duplicate_keys,
    _read_bounded,
    _safe_relative_file,
    inspect_corpus,
)

MAX_EVALUATION = 51  # Existing C++ evaluator has a strict argv bound.
RESPONSE_RE = re.compile(r"(positive|negative)_accepted=([0-9]+)/([0-9]+)\Z")


class PipelineRejected(ValueError):
    """Fixed non-sensitive rejection reason; never echo raw paths or audio."""


def _allowed_private_path(path: Path, repo_root: Path) -> bool:
    resolved = path.resolve()
    return resolved != repo_root and repo_root not in resolved.parents


def _load_checked_data(raw: bytes) -> dict:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
    except (ValueError, UnicodeError, CorpusError) as exc:
        raise PipelineRejected("manifest_changed_or_invalid") from exc
    if not isinstance(document, dict) or set(document) != {"schema", "samples"}:
        raise PipelineRejected("manifest_changed_or_invalid")
    return document


def _snapshot(manifest: Path, samples: list[dict]) -> dict[str, str]:
    """Retain file fingerprints privately; never print or persist them."""
    root = manifest.resolve().parent
    result = {}
    try:
        result["manifest"] = hashlib.sha256(_read_bounded(manifest, MAX_MANIFEST_BYTES)).hexdigest()
        for row in samples:
            path = _safe_relative_file(root, row["file"])
            result[row["id"]] = hashlib.sha256(_read_bounded(path, MAX_WAV_BYTES)).hexdigest()
    except (CorpusError, OSError, KeyError, TypeError) as exc:
        raise PipelineRejected("private_inputs_unavailable_or_changed") from exc
    return result


def prepare(manifest: Path, destination: Path) -> tuple[dict, dict, dict]:
    repo_root = Path(__file__).resolve().parents[3]
    if manifest.is_symlink() or destination.parent.is_symlink():
        raise PipelineRejected("private_symlink_rejected")
    try:
        manifest = manifest.resolve(strict=True)
        private_dir = destination.parent.resolve(strict=True)
    except OSError as exc:
        raise PipelineRejected("private_path_unavailable") from exc
    if (
        not manifest.name.endswith(".wake-corpus.json")
        or destination.suffix.lower() != ".swk1"
        or not _allowed_private_path(manifest, repo_root)
        or not _allowed_private_path(private_dir, repo_root)
        or destination.exists()
        or destination.is_symlink()
        or not private_dir.is_dir()
    ):
        raise PipelineRejected("unsafe_or_existing_private_output")

    try:
        raw_before = _read_bounded(manifest, MAX_MANIFEST_BYTES)
        audit = inspect_corpus(manifest)
        raw_after = _read_bounded(manifest, MAX_MANIFEST_BYTES)
    except (CorpusError, OSError) as exc:
        raise PipelineRejected("corpus_preflight_rejected") from exc
    if raw_before != raw_after:
        raise PipelineRejected("manifest_changed_during_preflight")
    if audit["status"] != "CORPUS_STRUCTURALLY_SCREENED":
        raise PipelineRejected("corpus_minimum_samples_missing")
    # A warning is not an acoustic diagnosis, but an automatic training
    # pipeline must not silently enroll clipped/DC-biased/noisy input.
    if audit["screening_warnings"]:
        raise PipelineRejected("corpus_quality_warnings_require_review")

    document = _load_checked_data(raw_after)
    grouped = {
        ("enrollment", "wake"): [],
        ("calibration", "wake"): [],
        ("calibration", "nonwake"): [],
        ("evaluation", "wake"): [],
        ("evaluation", "nonwake"): [],
    }
    for row in document["samples"]:
        grouped[(row["stage"], row["label"])].append(row)
    if not (
        1 <= len(grouped[("enrollment", "wake")]) <= 3
        and 5 <= len(grouped[("calibration", "wake")]) <= 32
        and 10 <= len(grouped[("calibration", "nonwake")]) <= 64
        and 2
        <= len(grouped[("evaluation", "wake")]) + len(grouped[("evaluation", "nonwake")])
        <= MAX_EVALUATION
    ):
        raise PipelineRejected("algorithm_input_bounds_exceeded")
    original_snapshot = _snapshot(manifest, document["samples"])
    if original_snapshot["manifest"] != hashlib.sha256(raw_before).hexdigest():
        raise PipelineRejected("manifest_changed_during_preflight")
    return audit, grouped, original_snapshot


def _require_unchanged(manifest: Path, grouped: dict, initial: dict[str, str]) -> None:
    samples = [row for group in grouped.values() for row in group]
    if _snapshot(manifest, samples) != initial:
        raise PipelineRejected("private_inputs_changed_during_processing")


def _build(compiler: list[str], source: Path, output: Path, core: Path) -> None:
    try:
        result = subprocess.run(
            [
                *compiler,
                "-std=c++20",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                "-I",
                str(core),
                str(source),
                "-o",
                str(output),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PipelineRejected("offline_cpp_compile_unavailable") from exc
    if result.returncode != 0:
        raise PipelineRejected("offline_cpp_compile_failed")


def _call(binary: Path, arguments: list[str], timeout_s: int) -> str:
    try:
        result = subprocess.run(
            [str(binary), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PipelineRejected("offline_cpp_stage_unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > 2048:
        raise PipelineRejected("offline_cpp_stage_rejected")
    return result.stdout


def _parse_evaluation(stdout: str, expected_positive: int, expected_negative: int) -> dict:
    lines = stdout.splitlines()
    if not lines or lines[0] != "UNVERIFIED_USER_LABELED_WAKE_EVALUATION":
        raise PipelineRejected("unexpected_evaluation_response")
    found = {}
    for line in lines[1:]:
        match = RESPONSE_RE.fullmatch(line)
        if match:
            kind, accepted_text, count_text = match.groups()
            if kind in found:
                raise PipelineRejected("duplicate_evaluation_field")
            accepted, count = int(accepted_text), int(count_text)
            if not 0 <= accepted <= count:
                raise PipelineRejected("invalid_evaluation_counts")
            found[kind] = {"accepted": accepted, "total": count}
    if (
        len(found) != 2
        or found["positive"]["total"] != expected_positive
        or found["negative"]["total"] != expected_negative
    ):
        raise PipelineRejected("unexpected_evaluation_counts")
    return found


def _private_paths(manifest: Path, samples: list[dict]) -> list[str]:
    root = manifest.resolve().parent
    # safe_relative_file was already verified. Repeat before each invocation.
    return [str(_safe_relative_file(root, row["file"])) for row in samples]


def _compiler_command(*, offline_zig: bool) -> list[str]:
    if offline_zig:
        uvx = shutil.which("uvx")
        if not uvx:
            raise PipelineRejected("uvx_unavailable_for_cached_zig")
        # Strictly no package retrieval during enrollment. An operator must
        # have explicitly cached this pinned compiler before using the flag.
        return [uvx, "--offline", "--from", "ziglang==0.15.2", "python-zig", "c++"]
    compiler = shutil.which("g++")
    if not compiler:
        raise PipelineRejected("gpp_compiler_unavailable")
    return [compiler]


def run_pipeline(
    manifest: Path, destination: Path, *, check_only: bool = False, offline_zig: bool = False
) -> dict:
    audit, grouped, original = prepare(manifest, destination)
    counts = audit["counts"]
    base = {
        "data_status": "CORPUS_STRUCTURALLY_SCREENED",
        "counts": counts,
        "source_labels_verified": False,
        "independent_recordings_proven": False,
        "actual_korean_wake_accuracy_proven": False,
        "false_wakes_per_hour_measured": False,
        "robot_or_microphone_accessed": False,
        "network_or_paid_api_used": False,
        "firmware_or_nvs_modified": False,
        "device_install_authorized": False,
    }
    if check_only:
        return {
            "status": "PRIVATE_CORPUS_READY_FOR_OFFLINE_TOOLCHAIN",
            **base,
            "profile_created": False,
            "independent_evaluation_run": False,
        }

    compiler = _compiler_command(offline_zig=offline_zig)

    tools = Path(__file__).resolve().parent
    core = tools.parent / "core"
    with tempfile.TemporaryDirectory(prefix="stackchan-wake-", dir=destination.parent) as tmp:
        location = Path(tmp)
        enrollment_binary = location / ("wake_enroll.exe" if os.name == "nt" else "wake_enroll")
        evaluation_binary = location / ("wake_eval.exe" if os.name == "nt" else "wake_eval")
        _build(compiler, tools / "wake_wav_enroll.cpp", enrollment_binary, core)
        _build(compiler, tools / "wake_wav_eval.cpp", evaluation_binary, core)
        _require_unchanged(manifest, grouped, original)

        temporary_profile = location / "candidate.swk1"
        enroll_args = []
        for key, flag in (
            (("enrollment", "wake"), "--template"),
            (("calibration", "wake"), "--holdout"),
            (("calibration", "nonwake"), "--negative"),
        ):
            for filename in _private_paths(manifest, grouped[key]):
                enroll_args.extend([flag, filename])
        enroll_args.extend(["--output", str(temporary_profile)])
        enrollment_out = _call(enrollment_binary, enroll_args, 180)
        if not enrollment_out.startswith("UNVERIFIED_PRIVATE_WAKE_PROFILE_WRITTEN\n"):
            raise PipelineRejected("unexpected_enrollment_response")
        try:
            validate_profile(_read_bounded(temporary_profile, 2507))
        except (ProtocolError, CorpusError, OSError) as exc:
            raise PipelineRejected("generated_profile_invalid") from exc
        _require_unchanged(manifest, grouped, original)

        eval_args = [str(temporary_profile)]
        for key, flag in (
            (("evaluation", "wake"), "--positive"),
            (("evaluation", "nonwake"), "--negative"),
        ):
            for filename in _private_paths(manifest, grouped[key]):
                eval_args.extend([flag, filename])
        evaluation_out = _call(evaluation_binary, eval_args, 180)
        result = _parse_evaluation(
            evaluation_out,
            len(grouped[("evaluation", "wake")]),
            len(grouped[("evaluation", "nonwake")]),
        )
        _require_unchanged(manifest, grouped, original)

        # Create a hard link to the exclusively generated private temp file:
        # fails rather than overwrites any existing profile or symlink.
        try:
            os.link(temporary_profile, destination, follow_symlinks=False)
        except OSError as exc:
            raise PipelineRejected("exclusive_profile_publication_failed") from exc
    return {
        "status": "UNVERIFIED_OFFLINE_PROFILE_AND_EVALUATION",
        **base,
        "profile_created": True,
        "independent_evaluation_run": True,
        "evaluation_user_labeled_counts": result,
        "explanation": (
            "The sample split was screened and the offline algorithm ran. "
            "Recording provenance, actual Korean recognition accuracy, "
            "and deployment safety have NOT been proven."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="private *.wake-corpus.json")
    parser.add_argument("--output", required=True, type=Path, help="NEW private SWK1 path")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="preflight without C++ compiler, SWK1 output, or independent evaluation",
    )
    parser.add_argument(
        "--offline-zig",
        action="store_true",
        help="use ONLY already-cached ziglang==0.15.2 via uvx --offline",
    )
    args = parser.parse_args(argv)
    try:
        result = run_pipeline(
            args.manifest,
            args.output,
            check_only=args.check_only,
            offline_zig=args.offline_zig,
        )
        exit_code = 0
    except (PipelineRejected, OSError, CorpusError) as exc:
        result = {
            "status": "REJECTED_PRIVATE_WAKE_PIPELINE",
            "reason": exc.args[0] if isinstance(exc, PipelineRejected) else "input_unavailable",
            "profile_created": False,
            "device_install_authorized": False,
            "robot_or_microphone_accessed": False,
            "network_or_paid_api_used": False,
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
