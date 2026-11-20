"""One-shot, OFFLINE, laptop-microphone -> original SWK1 C++ matcher.

No K151 microphone access. No continuous listening. No STT, GPT, TTS,
robot command, network call, audio file or user-voice upload.
Run with an explicit --listen; otherwise only process an existing WAV fixture.
"""

import argparse
import io
import json
import subprocess
import wave
from pathlib import Path

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
    """48kHz PCM16 -> 24kHz mono with low-pass FIR and simple energy trimming."""
    if samples.ndim != 1 or not 4800 <= len(samples) <= 144000:
        raise ProbeError("invalid_mic_audio_length")
    if samples.dtype != np.dtype("int16"):
        raise ProbeError("invalid_mic_audio_dtype")
    n = np.arange(-40, 41, dtype=np.float64)
    cut = 10500.0 / 48000.0
    fir = 2.0 * cut * np.sinc(2.0 * cut * n) * np.hamming(81)
    fir /= fir.sum()
    signal = np.convolve(samples.astype(np.float64), fir, mode="same")[::2]
    sample24 = np.rint(np.clip(signal, -32768, 32767)).astype(np.int16)
    block = 480  # 20ms
    complete = len(sample24) // block
    energy = (
        np.sqrt(
            np.mean(
                np.square(sample24[: complete * block].reshape(complete, block).astype(np.float64)),
                axis=1,
            )
        )
        / 32768.0
    )
    quiet_floor = float(np.percentile(energy, 20))
    threshold = max(0.002, quiet_floor * 3.0)
    active = np.flatnonzero(energy > threshold)
    if len(active) < 3:
        sample24.fill(0)
        return None
    # Preserve consonant onsets/trailing silence for the original MFCC model.
    # This is a prototype choice checked on same-voice TTS, not human-calibrated.
    context = 9600  # 400ms around activity; 100ms truncates the known wake clips.
    begin = max(0, int(active[0]) * block - context)
    end = min(len(sample24), (int(active[-1]) + 1) * block + context)
    trimmed = sample24[begin:end].copy()
    sample24.fill(0)
    if not MIN_SAMPLE_FRAMES_24K <= len(trimmed) <= 72000:
        trimmed.fill(0)
        return None
    return trimmed


def record_laptop_mic(device: int, seconds: float) -> tuple[bytes | None, int]:
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise ProbeError("sounddevice_and_numpy_not_installed") from exc
    if not (0.2 <= seconds <= MAX_AUDIO_SECONDS):
        raise ProbeError("invalid_record_duration")
    try:
        desc = sd.query_devices(device, "input")
        if not desc["max_input_channels"]:
            raise ProbeError("input_device_not_a_microphone")
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
    except (OSError, ValueError, RuntimeError) as exc:
        raise ProbeError("mic_unavailable_or_permission_denied") from exc

    try:
        trimmed = resample_and_trim_48k(samples, np)
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
    parser.add_argument("--device", type=int, help="explicit notebook microphone device index")
    parser.add_argument("--seconds", type=float, default=2.5)
    args = parser.parse_args(argv)
    try:
        probe = safe_file(args.probe_exe, 5_000_000)
        profile = safe_file(args.profile, 2507)
        if args.fixture is not None:
            wav = safe_file(args.fixture, MAX_WAV_BYTES).read_bytes()
            origin = "EXISTING_LOCAL_FIXTURE"
            frames = None
        else:
            if args.device is None:
                raise ProbeError("explicit_input_device_required")
            wav, frames = record_laptop_mic(args.device, args.seconds)
            origin = "NOTEBOOK_MIC_NOT_K151"
        status = "NO_SPEECH_ACTIVITY" if wav is None else classify_wav(probe, profile, wav)
        result = {
            "status": status,
            "source": origin,
            "k151_microphone_verified": False,
            "k151_firmware_modified": False,
            "recorded_audio_written_to_disk": False,
            "network_or_paid_api_used": False,
        }
        if frames is not None:
            result["trimmed_frames_24khz"] = frames
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ProbeError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ProbeError) else "local_io_unavailable"
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
