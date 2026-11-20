"""Offline CPU Whisper tiny verification AFTER original C++ DTW wake gate.

No cloud calls, pretrained weights only from an explicitly supplied pinned
local directory. The single Korean ASR result must be EXACTLY "조수야";
rejected stage-1 clips are never sent to ASR. No fuzzy words, prompting
with target phrases, fallback, speaker verification or hardware activation.

This host-only prototype is NOT a K151 or real-human acoustic validation.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from evaluate_fresh_frozen_heami import load_new_holdout
from vosk_wake_second_stage import (
    OfflineVoskRejected,
    exact_wake_transcript,
    read_24k_mono_pcm16_wav,
    resample_24k_pcm16_to_16k,
    stage1_probe,
)
from wake_corpus_audit import (
    MAX_MANIFEST_BYTES,
    _object_without_duplicate_keys,
    _read_bounded,
    _safe_relative_file,
)

MODEL_DIRECTORY_NAME = "faster-whisper-tiny"
MODEL_REPOSITORY = "Systran/faster-whisper-tiny"
MODEL_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
MODEL_WEIGHTS_SHA256 = "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1"
MODEL_CONFIG_SHA256 = "a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8"
MODEL_TOKENIZER_SHA256 = "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"
ASR_BEAM_SIZE = 5
ASR_CPU_THREADS = 4
ASR_MAX_NEW_TOKENS = 32


class OfflineWhisperRejected(ValueError):
    """Emit fixed non-sensitive error reasons; never print audio or paths."""


def _sha256_bounded(path: Path, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise OfflineWhisperRejected("missing_or_linked_model_file")
    if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise OfflineWhisperRejected("model_size_invalid")
    hash_value = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hash_value.update(chunk)
    return hash_value.hexdigest()


def verified_local_model(model_dir: Path) -> bool:
    # Pin exact model conversion AND repo revision; refuse arbitrary model dirs.
    # This is file-integrity checking, NOT independent vendor signing.
    if model_dir.name != MODEL_DIRECTORY_NAME or model_dir.is_symlink():
        return False
    if not model_dir.is_dir():
        return False
    try:
        return all(
            _sha256_bounded(model_dir / filename, bound) == expected
            for filename, bound, expected in (
                ("model.bin", 85_000_000, MODEL_WEIGHTS_SHA256),
                ("config.json", 200_000, MODEL_CONFIG_SHA256),
                ("tokenizer.json", 4_000_000, MODEL_TOKENIZER_SHA256),
            )
        )
    except (OSError, OfflineWhisperRejected):
        return False


def load_pinned_whisper_model(model_dir: Path) -> object:
    if not verified_local_model(model_dir):
        raise OfflineWhisperRejected("pinned_local_whisper_model_not_available")
    # Explicitly prevent hidden model downloads at inference time.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(
            str(model_dir),
            device="cpu",
            compute_type="int8",
            cpu_threads=ASR_CPU_THREADS,
            num_workers=1,
            local_files_only=True,
        )
    except (OSError, ImportError, RuntimeError, ValueError) as exc:
        raise OfflineWhisperRejected("local_whisper_model_load_failed") from exc


def transcript_from_whisper(model: object, pcm16: bytes) -> str:
    try:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        segments, info = model.transcribe(
            audio,
            language="ko",
            task="transcribe",
            beam_size=ASR_BEAM_SIZE,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=None,
            hotwords=None,
            vad_filter=False,
            without_timestamps=True,
            max_new_tokens=ASR_MAX_NEW_TOKENS,
        )
        if getattr(info, "language", None) != "ko":
            raise OfflineWhisperRejected("unexpected_asr_language")
        transcript = " ".join(seg.text for seg in segments)
        if len(transcript) > 80:
            raise OfflineWhisperRejected("asr_transcript_excessive")
        return transcript
    except OfflineWhisperRejected:
        raise
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        raise OfflineWhisperRejected("offline_whisper_inference_failed") from exc


def evaluate_whisper_stage2(manifest: Path, binary: Path, profile: Path, model_dir: Path) -> dict:
    # Load the local recognizer once; no network API may receive any audio.
    model = load_pinned_whisper_model(model_dir)
    labels = load_new_holdout(manifest)  # exactly 4 positive + 12 nonwake.
    try:
        document = json.loads(
            _read_bounded(manifest, MAX_MANIFEST_BYTES).decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        rows = document["samples"]
        paths = {row["id"]: _safe_relative_file(manifest.parent, row["file"]) for row in rows}
        if len(rows) != len(labels) or len(paths) != len(labels):
            raise OfflineWhisperRejected("manifest_size_or_ids_changed")
    except (ValueError, UnicodeError, OSError, TypeError, KeyError, OfflineVoskRejected) as exc:
        raise OfflineWhisperRejected("manifest_unavailable_or_invalid") from exc

    first = {"wake": 0, "nonwake": 0}
    final = {"wake": 0, "nonwake": 0}
    calls = 0
    begun = time.perf_counter()
    for row in labels:
        path = paths[row["id"]]
        try:
            stage1_accepted = stage1_probe(binary, profile, path)
        except OfflineVoskRejected as exc:
            raise OfflineWhisperRejected("stage1_rejected_invalid_input") from exc
        if not stage1_accepted:
            continue
        first[row["label"]] += 1
        try:
            raw_pcm = read_24k_mono_pcm16_wav(path)
            pcm16 = resample_24k_pcm16_to_16k(raw_pcm)
        except OfflineVoskRejected as exc:
            raise OfflineWhisperRejected("offline_wav_resample_failed") from exc
        transcription = transcript_from_whisper(model, pcm16)
        calls += 1
        if exact_wake_transcript(transcription):
            final[row["label"]] += 1
    return {
        "status": "UNVERIFIED_LOCAL_WHISPER_TINY_STAGE2",
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_WEIGHTS_SHA256,
        "stage1_accepted": first,
        "two_stage_accepted": final,
        "denominators": {"wake": 4, "nonwake": 12},
        "stage2_asr_invocations": calls,
        "local_cpu_wall_elapsed_s": round(time.perf_counter() - begun, 3),
        "asr_model_loaded_from_local_disk": True,
        "source_audio_is_same_heami_synthetic_voice": True,
        "real_speaker_independence_proven": False,
        "confidence_calibrated": False,
        "real_false_wakes_per_hour_proven": False,
        "physical_robot_accessed": False,
        "runtime_network_or_paid_api_used": False,
        "device_install_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--stage1-binary", required=True, type=Path)
    parser.add_argument("--stage1-profile", required=True, type=Path)
    parser.add_argument("--whisper-model-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate_whisper_stage2(
            args.manifest,
            args.stage1_binary,
            args.stage1_profile,
            args.whisper_model_dir,
        )
        code = 0
    except (OfflineWhisperRejected, OSError, ValueError, RuntimeError) as exc:
        result = {
            "status": "REJECTED_LOCAL_WHISPER_STAGE2",
            "reason": str(exc)
            if isinstance(exc, OfflineWhisperRejected)
            else "offline_execution_or_input_failed",
            "physical_robot_accessed": False,
            "runtime_network_or_paid_api_used": False,
            "device_install_authorized": False,
        }
        code = 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
