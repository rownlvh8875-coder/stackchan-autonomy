"""Offline research-only two-stage Korean wake confirmation with LOCAL Vosk.

Stage 1: existing C++ SWK1 MFCC/DTW probe (must accept).
Stage 2: a locally installed Vosk Korean model transcribes the SAME PCM and
must return EXACTLY the selected phrase (default "조수").

No network, microphones, robots, NVS, OTA or paid APIs. Never authorizes
hardware installation. Confidence values are NOT assumed calibrated.
The optional Vosk package/model are not bundled with this repository.
"""

import argparse
import array
import json
import math
import re
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

from evaluate_fresh_frozen_heami import load_new_holdout

EXPECTED_KOREAN_MODEL_DIR = "vosk-model-small-ko-0.22"
SOURCE_RATE_HZ = 24000
RECOGNIZER_RATE_HZ = 16000
MAX_WAV_FILE_BYTES = 196608
MAX_TRANSCRIPT_LENGTH = 80
PUNCTUATION = ".,!?。！？"


class OfflineVoskRejected(ValueError):
    """Stable diagnostics only; never echo private audio or file paths."""


DEFAULT_WAKE_PHRASE = "조수"
SUPPORTED_WAKE_PHRASES = ("조수", "조수야")


def exact_wake_transcript(text: object, *, wake_phrase: str = DEFAULT_WAKE_PHRASE) -> bool:
    """NFKC+trailing punctuation; exact word only, no substring/fuzzy."""
    if wake_phrase not in SUPPORTED_WAKE_PHRASES:
        return False
    if not isinstance(text, str) or not text or len(text) > MAX_TRANSCRIPT_LENGTH:
        return False
    normalized = unicodedata.normalize("NFKC", text).strip()
    normalized = normalized.rstrip(PUNCTUATION).strip()
    if not re.fullmatch(r"[가-힣\s]+", normalized):
        return False
    return "".join(normalized.split()) == wake_phrase


def _resampler_kernels() -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Match C++ source's 24k->16k windowed-sinc 33-tap design."""
    generated = []
    radius = 16
    cutoff = 0.60
    for phase in (0, 1):
        taps = []
        for j in range(-radius, radius + 1):
            x = j - phase * 0.5
            sinc = 1.0 if abs(x) < 1e-6 else math.sin(math.pi * cutoff * x) / (math.pi * cutoff * x)
            window = 0.5 * (1.0 + math.cos(math.pi * x / (radius + 0.5)))
            taps.append(cutoff * sinc * window)
        total = sum(taps)
        generated.append(tuple(value / total for value in taps))
    return generated[0], generated[1]


KERNELS_24_TO_16 = _resampler_kernels()


def resample_24k_pcm16_to_16k(pcm: bytes) -> bytes:
    if len(pcm) % 2 or not 2400 <= len(pcm) // 2 <= 72000:
        raise OfflineVoskRejected("invalid_pcm_24k_frame_count")
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    result = array.array("h")
    result_append = result.append
    for n in range(len(samples) * 2 // 3):
        phase = n & 1
        center = (3 * n) // 2
        acc = 0.0
        weights = KERNELS_24_TO_16[phase]
        for index, weight in enumerate(weights):
            position = center + index - 16
            if 0 <= position < len(samples):
                acc += samples[position] * weight
        result_append(max(-32768, min(32767, round(acc))))
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def read_24k_mono_pcm16_wav(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OfflineVoskRejected("wav_missing_or_symlink")
    try:
        if path.stat().st_size > MAX_WAV_FILE_BYTES:
            raise OfflineVoskRejected("wav_file_oversize")
        with wave.open(str(path), "rb") as stream:
            if (
                stream.getnchannels() != 1
                or stream.getsampwidth() != 2
                or stream.getframerate() != SOURCE_RATE_HZ
                or stream.getcomptype() != "NONE"
                or not 2400 <= stream.getnframes() <= 72000
            ):
                raise OfflineVoskRejected("wav_format_not_24k_mono_pcm16")
            frames = stream.readframes(stream.getnframes())
            if len(frames) != stream.getnframes() * 2:
                raise OfflineVoskRejected("wav_pcm_truncated")
            return frames
    except (OSError, EOFError, wave.Error) as exc:
        raise OfflineVoskRejected("wav_file_unreadable") from exc


def valid_local_model_directory(model_dir: Path) -> bool:
    # The process itself never downloads models. It can only use an explicitly
    # supplied, already installed local official Korean Vosk small model.
    if model_dir.name != EXPECTED_KOREAN_MODEL_DIR or model_dir.is_symlink():
        return False
    if not model_dir.is_dir():
        return False
    return all(
        (model_dir / sub).is_dir() and not (model_dir / sub).is_symlink()
        for sub in ("am", "conf", "graph", "ivector")
    )


def stage1_probe(binary: Path, profile: Path, wav: Path) -> bool:
    if any(p.is_symlink() or not p.is_file() for p in (binary, profile, wav)):
        raise OfflineVoskRejected("invalid_offline_stage1_input")
    try:
        completed = subprocess.run(
            [str(binary), str(profile), str(wav)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfflineVoskRejected("offline_stage1_probe_unavailable") from exc
    if completed.returncode != 0:
        raise OfflineVoskRejected("offline_stage1_probe_rejected")
    if completed.stdout == "OFFLINE_STAGE1_ACCEPT\n":
        return True
    if completed.stdout == "OFFLINE_STAGE1_REJECT\n":
        return False
    raise OfflineVoskRejected("offline_stage1_unrecognized_response")


def transcript_from_offline_vosk(model: object, pcm16: bytes) -> str:
    # Deferred import: CI/core tests do not require Vosk or a giant model.
    try:
        from vosk import KaldiRecognizer  # type: ignore[import-not-found]

        recognizer = KaldiRecognizer(model, RECOGNIZER_RATE_HZ)
        recognizer.AcceptWaveform(pcm16)
        result = json.loads(recognizer.FinalResult())
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        raise OfflineVoskRejected("offline_asr_inference_failed") from exc
    if not isinstance(result, dict) or set(result) != {"text"}:
        raise OfflineVoskRejected("offline_asr_response_invalid")
    text = result["text"]
    if not isinstance(text, str) or len(text) > MAX_TRANSCRIPT_LENGTH:
        raise OfflineVoskRejected("offline_asr_transcript_invalid")
    return text


def evaluate_cascade(
    manifest: Path,
    stage1_binary: Path,
    stage1_profile: Path,
    vosk_model_dir: Path,
    *,
    wake_phrase: str = DEFAULT_WAKE_PHRASE,
) -> dict:
    if not valid_local_model_directory(vosk_model_dir):
        raise OfflineVoskRejected("offline_korean_model_not_installed")
    try:
        import vosk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OfflineVoskRejected("vosk_package_not_installed") from exc

    vosk.SetLogLevel(-1)
    try:
        model = vosk.Model(str(vosk_model_dir))
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfflineVoskRejected("offline_korean_model_load_failed") from exc
    clips = load_new_holdout(manifest)  # requires 4 wake and 12 nonwake.
    # load_new_holdout reads/validates PCM but not original filesystem path.
    # Strict manifest-relative locator is used below only for C++ stage 1.
    from wake_corpus_audit import (
        MAX_MANIFEST_BYTES,
        _object_without_duplicate_keys,
        _read_bounded,
        _safe_relative_file,
    )

    try:
        data = json.loads(
            _read_bounded(manifest, MAX_MANIFEST_BYTES).decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        rows = data["samples"]
        if not isinstance(rows, list) or len(rows) != len(clips):
            raise OfflineVoskRejected("manifest_changed_or_invalid")
        # Match on immutable ids, reject anything inconsistent.
        lookup = {item["id"]: _safe_relative_file(manifest.parent, item["file"]) for item in rows}
        if len(lookup) != len(clips):
            raise OfflineVoskRejected("duplicate_manifest_sample_id")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise OfflineVoskRejected("manifest_read_failed") from exc

    stage1 = {"wake": 0, "nonwake": 0}
    cascade = {"wake": 0, "nonwake": 0}
    asr_checked = 0
    started = time.perf_counter()
    for item in clips:
        path = lookup[item["id"]]
        # All full-batch errors must remain errors rather than false negatives.
        first = stage1_probe(stage1_binary, stage1_profile, path)
        if not first:
            continue  # Do not invoke second-stage ASR for rejected speech.
        label = item["label"]
        stage1[label] += 1
        # Strictly re-read local WAV; never upload audio or transmit it.
        pcm16 = resample_24k_pcm16_to_16k(read_24k_mono_pcm16_wav(path))
        recognized = transcript_from_offline_vosk(model, pcm16)
        asr_checked += 1
        if exact_wake_transcript(recognized, wake_phrase=wake_phrase):
            cascade[label] += 1

    return {
        "status": "UNVERIFIED_LOCAL_HEAMI_VOSK_CASCADE",
        "vosk_model": EXPECTED_KOREAN_MODEL_DIR,
        "stage1_accepted": stage1,
        "two_stage_accepted": cascade,
        "denominators": {"wake": 4, "nonwake": 12},
        "asr_invocations_after_stage1_accept": asr_checked,
        "local_host_wall_elapsed_s": round(time.perf_counter() - started, 3),
        "same_synthetic_voice_only": True,
        "asr_confidence_calibrated": False,
        "different_human_speakers_tested": False,
        "real_false_wakes_per_hour_measured": False,
        "model_has_not_been_tested_on_esp32": True,
        "robot_hardware_accessed": False,
        "paid_api_or_network_used": False,
        "device_install_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--stage1-binary", required=True, type=Path)
    parser.add_argument("--stage1-profile", required=True, type=Path)
    parser.add_argument("--vosk-model-dir", required=True, type=Path)
    parser.add_argument(
        "--wake-phrase", choices=SUPPORTED_WAKE_PHRASES, default=DEFAULT_WAKE_PHRASE
    )
    args = parser.parse_args()
    try:
        report = evaluate_cascade(
            args.manifest,
            args.stage1_binary,
            args.stage1_profile,
            args.vosk_model_dir,
            wake_phrase=args.wake_phrase,
        )
        status = 0
    except (OfflineVoskRejected, OSError, ValueError, RuntimeError) as exc:
        report = {
            "status": "REJECTED_LOCAL_VOSK_TWO_STAGE_TEST",
            "reason": str(exc)
            if isinstance(exc, OfflineVoskRejected)
            else "offline_input_or_model_unavailable",
            "device_install_authorized": False,
            "paid_api_or_network_used": False,
            "robot_hardware_accessed": False,
        }
        status = 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
