"""Private, offline wake-word WAV corpus preflight. No recording, device or network.

Checks role/session separation, exact PCM duplicate leakage, and simple waveform
quality indicators. It DOES NOT validate the user's labels, the independence
of recording sessions, Korean speech recognition, or installation readiness.
"""

import argparse
import array
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path, PurePosixPath

SCHEMA = "stackchan-private-wake-corpus-v1"
MAX_MANIFEST_BYTES = 65536
MAX_WAV_BYTES = 196608
MAX_SAMPLES = 200
MIN_PCM = 2400
MAX_PCM = 72000
MIN_COUNTS = {
    ("enrollment", "wake"): 1,
    ("calibration", "wake"): 5,
    ("calibration", "nonwake"): 10,
    ("evaluation", "wake"): 1,
    ("evaluation", "nonwake"): 1,
}
SAMPLE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}\Z")
FILE_PART = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")


class CorpusError(ValueError):
    """Only fixed non-sensitive reasons are allowed in public diagnostics."""


def _object_without_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CorpusError("duplicate_manifest_key")
        out[key] = value
    return out


def _read_bounded(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CorpusError("missing_or_linked_file")
    try:
        with path.open("rb") as f:
            result = f.read(max_bytes + 1)
    except OSError as exc:
        raise CorpusError("file_unreadable") from exc
    if not result or len(result) > max_bytes:
        raise CorpusError("file_size_invalid")
    return result


def _safe_relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or len(relative) > 200 or "\\" in relative:
        raise CorpusError("invalid_relative_filename")
    parts = PurePosixPath(relative).parts
    if not parts or any(part in ("", ".", "..") or not FILE_PART.fullmatch(part) for part in parts):
        raise CorpusError("invalid_relative_filename")
    if not relative.lower().endswith(".wav"):
        raise CorpusError("not_wav")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise CorpusError("symlink_not_allowed")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CorpusError("file_outside_corpus") from exc
    return candidate


def _decode_canonical_wav(data: bytes) -> bytes:
    # Match the accepted RIFF/PCM16 contract of core/wake_wav_pcm.hpp.
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise CorpusError("wav_header_invalid")
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise CorpusError("wav_riff_length_mismatch")
    pos, has_fmt, pcm = 12, False, None
    while pos < len(data):
        if len(data) - pos < 8:
            raise CorpusError("wav_chunk_header_invalid")
        kind = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        start = pos + 8
        if size > len(data) - start:
            raise CorpusError("wav_chunk_truncated")
        if kind == b"fmt ":
            if has_fmt or pcm is not None or size != 16:
                raise CorpusError("wav_format_chunk_invalid")
            codec, channels, rate, byte_rate, align, depth = struct.unpack_from(
                "<HHIIHH", data, start
            )
            if (codec, channels, rate, byte_rate, align, depth) != (1, 1, 24000, 48000, 2, 16):
                raise CorpusError("wav_format_not_24k_mono_pcm16")
            has_fmt = True
        elif kind == b"data":
            if not has_fmt or pcm is not None or size % 2 or not MIN_PCM <= size // 2 <= MAX_PCM:
                raise CorpusError("wav_pcm_length_invalid")
            pcm = data[start : start + size]
        pos = start + size + size % 2
        if pos > len(data):
            raise CorpusError("wav_padding_invalid")
    if not has_fmt or pcm is None or pos != len(data):
        raise CorpusError("wav_missing_pcm")
    return pcm


def _waveform_stats(pcm: bytes) -> dict:
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    n = len(samples)
    peak = max(abs(v) for v in samples)
    average = sum(samples) / n
    energy = sum(v * v for v in samples) / n
    rms = math.sqrt(energy) / 32768.0
    # Numerical cutoffs below are screening heuristics, NOT acoustic calibration.
    if peak / 32768.0 < 0.003 or energy / 32768.0**2 < 1e-6:
        raise CorpusError("wav_silence_or_below_core_energy_gate")
    warnings = []
    if sum(abs(v) >= 32700 for v in samples) * 100 >= n:
        warnings.append("possible_clipping_over_1_percent")
    if abs(average) / 32768.0 > 0.10:
        warnings.append("large_dc_offset")
    if rms < 0.01:
        warnings.append("low_rms_screening_only")
    return {"frames": n, "warnings": warnings}


def inspect_corpus(manifest_path: Path) -> dict:
    raw = _read_bounded(manifest_path, MAX_MANIFEST_BYTES)
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
    except CorpusError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise CorpusError("manifest_json_invalid") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "samples"}
        or (document["schema"] != SCHEMA)
    ):
        raise CorpusError("manifest_schema_invalid")
    samples = document["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
        raise CorpusError("manifest_sample_count_invalid")

    root = manifest_path.resolve().parent
    counts = {f"{group}_{label}": 0 for group, label in MIN_COUNTS}
    sessions = {"enrollment": set(), "calibration": set(), "evaluation": set()}
    used_ids, used_paths, pcm_hashes = set(), set(), set()
    observed_warnings = {}
    frames_by_group = {group: [] for group in sessions}
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {
            "id",
            "stage",
            "label",
            "session",
            "file",
        }:
            raise CorpusError("sample_schema_invalid")
        identifier = sample["id"]
        stage, label, session = sample["stage"], sample["label"], sample["session"]
        if not all(
            isinstance(x, str) and SAMPLE_ID.fullmatch(x)
            for x in (identifier, stage, label, session)
        ):
            raise CorpusError("sample_metadata_invalid")
        if stage not in sessions or (stage, label) not in MIN_COUNTS:
            raise CorpusError("unknown_stage_or_label")
        if identifier in used_ids:
            raise CorpusError("sample_id_duplicate")
        used_ids.add(identifier)
        path = _safe_relative_file(root, sample["file"])
        if path in used_paths:
            raise CorpusError("sample_path_duplicate")
        used_paths.add(path)
        pcm = _decode_canonical_wav(_read_bounded(path, MAX_WAV_BYTES))
        fingerprint = hashlib.sha256(pcm).digest()
        if fingerprint in pcm_hashes:
            raise CorpusError("exact_pcm_duplicate_across_corpus")
        pcm_hashes.add(fingerprint)
        info = _waveform_stats(pcm)
        frames_by_group[stage].append(info["frames"])
        for warning in info["warnings"]:
            observed_warnings[warning] = observed_warnings.get(warning, 0) + 1
        counts[f"{stage}_{label}"] += 1
        sessions[stage].add(session)

    # Session labels are self-reported, and this test cannot prove identity.
    if any(
        sessions[a] & sessions[b]
        for a, b in (
            ("enrollment", "calibration"),
            ("enrollment", "evaluation"),
            ("calibration", "evaluation"),
        )
    ):
        raise CorpusError("declared_session_leakage")
    missing = [
        f"{stage}_{label}"
        for (stage, label), minimum in MIN_COUNTS.items()
        if counts[f"{stage}_{label}"] < minimum
    ]
    return {
        "status": "CORPUS_COUNTS_INCOMPLETE" if missing else "CORPUS_STRUCTURALLY_SCREENED",
        "counts": counts,
        "missing_minimum_groups": missing,
        "total_files": len(samples),
        "distinct_declared_sessions_by_stage": {
            stage: len(values) for stage, values in sessions.items()
        },
        "duration_ranges_ms": {
            stage: {"min": min(values) * 1000 // 24000, "max": max(values) * 1000 // 24000}
            for stage, values in frames_by_group.items()
            if values
        },
        "screening_warnings": observed_warnings,
        "recording_independence_proven": False,
        "speaker_identity_proven": False,
        "label_correctness_proven": False,
        "korean_wake_accuracy_proven": False,
        "safe_to_install": False,
        "prerecorded_audio_files_read": True,
        "live_microphone_or_robot_accessed": False,
        "network_accessed": False,
        "audio_files_modified": False,
        "explanation": "Only local format, declared-split, duplicate-PCM and heuristic quality checks.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="private manifest with relative WAV filenames")
    arguments = parser.parse_args(argv)
    try:
        report = inspect_corpus(arguments.manifest)
        code = 0 if report["status"] == "CORPUS_STRUCTURALLY_SCREENED" else 2
    except (CorpusError, OSError) as exc:
        report = {
            "status": "REJECTED_PRIVATE_WAKE_CORPUS",
            "reason": str(exc) if isinstance(exc, CorpusError) else "file_unavailable",
            "safe_to_install": False,
            "live_microphone_or_robot_accessed": False,
            "network_accessed": False,
            "audio_files_modified": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
