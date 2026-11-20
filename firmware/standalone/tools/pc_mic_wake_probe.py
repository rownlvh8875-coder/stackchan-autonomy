"""One-shot, OFFLINE, laptop-microphone -> original SWK1 C++ matcher.

No K151 microphone access. No continuous listening. No STT, GPT, TTS,
robot command, network call, audio file or user-voice upload.
Run with an explicit --listen; otherwise only process an existing WAV fixture.
"""

import argparse
import io
import json
import subprocess
import time
import tracemalloc
import wave
from pathlib import Path

from pc_mic_audio import AudioError, analyze_48k, require_device, select_microphone
from pc_mic_profile import EnrollmentError, score_wav

MIN_SAMPLE_FRAMES_24K = 2400
MAX_WAV_BYTES = 196608
MAX_AUDIO_SECONDS = 3.0


class ProbeError(ValueError):
    pass


def safe_file(path: Path, limit: int) -> Path:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ProbeError("missing_or_invalid_local_file")
    return path


def classify_wav(probe: Path, profile: Path, wav: bytes) -> str:
    if not 44 <= len(wav) <= MAX_WAV_BYTES:
        raise ProbeError("invalid_wav_size")
    try:
        result = subprocess.run(
            [str(probe), str(profile), "-"],
            input=wav,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError("probe_binary_failed") from exc
    if result.returncode != 0:
        raise ProbeError("probe_rejected_input")
    output = result.stdout.strip()
    if output == b"OFFLINE_STAGE1_ACCEPT":
        return "UNVERIFIED_MATCH"
    if output == b"OFFLINE_STAGE1_REJECT":
        return "UNVERIFIED_NO_MATCH"
    raise ProbeError("unknown_probe_result")


def resample_and_trim_48k(samples, np):
    """Compatibility wrapper; recording and enrollment share the same transform."""
    return analyze_48k(samples, np)[0]


def record_laptop_mic(
    device: int, seconds: float, *, expected_identity=None, diagnostics=None
) -> tuple[bytes | None, int]:
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise ProbeError("sounddevice_and_numpy_not_installed") from exc
    if not (0.2 <= seconds <= MAX_AUDIO_SECONDS):
        raise ProbeError("invalid_record_duration")
    try:
        identity = require_device(sd, device, expected_identity)
        sd.check_input_settings(device=device, channels=1, samplerate=48000, dtype="int16")
        print(
            json.dumps(
                {
                    "stage": "RECORDING_NOTEBOOK_MIC_ONLY",
                    "seconds": seconds,
                    "sample_rate": 48000,
                    "device_index": device,
                    "audio_file_created": False,
                    "robot_used": False,
                }
            ),
            flush=True,
        )
        samples = sd.rec(
            int(seconds * 48000),
            samplerate=48000,
            channels=1,
            device=device,
            dtype="int16",
            blocking=True,
        )[:, 0].copy()
    except AudioError:
        raise
    except Exception as exc:
        raise ProbeError("mic_unavailable_or_permission_denied") from exc

    try:
        require_device(sd, device, identity)
        trimmed, details = analyze_48k(samples, np)
        if diagnostics is not None:
            diagnostics.update(details)
        try:
            status = sd.get_status()
        except Exception as exc:
            if trimmed is not None:
                trimmed.fill(0)
            raise ProbeError("input_status_unavailable") from exc
        if status:
            if trimmed is not None:
                trimmed.fill(0)
            raise ProbeError("input_overflow_or_underflow")
    finally:
        samples.fill(0)
    if trimmed is None:
        return None, 0
    try:
        frames = len(trimmed)
        target = io.BytesIO()
        with wave.open(target, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(trimmed.astype("<i2", copy=False).tobytes())
        return target.getvalue(), frames
    finally:
        trimmed.fill(0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-exe", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="existing local WAV, no microphone opened")
    source.add_argument("--listen", action="store_true", help="one short notebook mic recording")
    device = parser.add_mutually_exclusive_group()
    device.add_argument("--device", type=int, help="explicit notebook microphone device index")
    device.add_argument(
        "--choose-device", action="store_true", help="list and explicitly select a microphone"
    )
    parser.add_argument(
        "--diagnostics", action="store_true", help="numeric quality, distance and timing only"
    )
    parser.add_argument("--seconds", type=float, default=2.5)
    args = parser.parse_args(argv)
    try:
        details = {}
        probe = safe_file(args.probe_exe, 5_000_000)
        profile = safe_file(args.profile, 2507)
        if args.fixture is not None:
            wav = safe_file(args.fixture, MAX_WAV_BYTES).read_bytes()
            origin = "EXISTING_LOCAL_FIXTURE"
            frames = None
        else:
            if args.device is None and not args.choose_device:
                raise ProbeError("explicit_input_device_required")
            device, identity = select_microphone(args.device, args.choose_device)
            wav, frames = record_laptop_mic(
                device, args.seconds, expected_identity=identity, diagnostics=details
            )
            origin = "NOTEBOOK_MIC_NOT_K151"
        tracemalloc.start()
        started = time.perf_counter()
        try:
            status = "NO_SPEECH_ACTIVITY" if wav is None else classify_wav(probe, profile, wav)
            match = (
                score_wav(probe, profile.read_bytes(), wav)
                if wav is not None and args.diagnostics
                else None
            )
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        elapsed_ms = (time.perf_counter() - started) * 1000
        result = {
            "status": status,
            "source": origin,
            "k151_microphone_verified": False,
            "k151_firmware_modified": False,
            "recorded_audio_written_to_disk": False,
            "network_or_paid_api_used": False,
        }
        if args.diagnostics:
            result.update(
                quality=details,
                match=match,
                wake_detected=status == "UNVERIFIED_MATCH",
                processing_ms=round(elapsed_ms, 3),
                python_traced_peak_bytes=peak_bytes,
            )
            if match is not None:
                result["distance_margin_q8"] = round(match["limit_q8"] - match["distance_q8"], 3)
        if frames is not None:
            result["trimmed_frames_24khz"] = frames
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print(
            json.dumps({"status": "PC_MIC_TEST_CANCELLED", "recorded_audio_written_to_disk": False})
        )
        return 130
    except (ProbeError, AudioError, EnrollmentError, OSError, ValueError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, (ProbeError, AudioError, EnrollmentError))
            else "local_io_unavailable"
        )
        print(
            json.dumps(
                {
                    "status": "OFFLINE_PC_WAKE_TEST_REJECTED",
                    "reason": reason,
                    "k151_hardware_accessed": False,
                    "network_or_paid_api_used": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
