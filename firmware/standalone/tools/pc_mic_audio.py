"""Bounded local PCM analysis. No audio IO, storage, recognition or network here."""

import hashlib
import json
import math


class AudioError(ValueError):
    pass


def device_identity(sd, device):
    try:
        desc = sd.query_devices(device, "input")
        if desc["max_input_channels"] < 1:
            raise AudioError("input_device_not_a_microphone")
        api = sd.query_hostapis(desc["hostapi"])["name"]
        identity = [desc["name"], api, desc["max_input_channels"], desc["default_samplerate"]]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError("input_device_unavailable") from exc


def require_device(sd, device, expected):
    current = device_identity(sd, device)
    if expected is not None and current != expected:
        raise AudioError("input_device_changed")
    return current


def analyze_48k(samples, np):
    """Keep the legacy FIR/400ms trim, expose why a sample is unsuitable to enroll.

    Activity touching a capture edge is a *risk*, not evidence of missing phonemes.
    Neither energy nor acoustic matching proves which word was actually spoken.
    """
    if samples.ndim != 1 or not 4800 <= len(samples) <= 144000:
        raise AudioError("invalid_mic_audio_length")
    if samples.dtype != np.dtype("int16"):
        raise AudioError("invalid_mic_audio_dtype")
    raw = samples.astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(raw * raw)))
    peak = float(np.max(np.abs(raw)))
    clipped = float(np.mean(np.abs(samples.astype(np.int32)) >= 32760))
    n = np.arange(-40, 41, dtype=np.float64)
    cut = 10500.0 / 48000.0
    fir = 2.0 * cut * np.sinc(2.0 * cut * n) * np.hamming(81)
    fir /= fir.sum()
    filtered = np.convolve(samples.astype(np.float64), fir, mode="same")[::2]
    sample24 = np.rint(np.clip(filtered, -32768, 32767)).astype(np.int16)
    raw.fill(0)
    filtered.fill(0)
    block = 480
    complete = len(sample24) // block
    energy = (
        np.sqrt(
            np.mean(
                sample24[: complete * block].reshape(complete, block).astype(float) ** 2, axis=1
            )
        )
        / 32768.0
    )
    floor = float(np.percentile(energy, 20))
    threshold = max(0.002, floor * 3.0)
    active = np.flatnonzero(energy > threshold)
    issues = []
    if clipped >= 0.001:
        issues.append("CLIPPING")
    diagnostics = {
        "input_sample_rate": 48000,
        "input_channels": 1,
        "input_bits": 16,
        "input_frames_48khz": len(samples),
        "resampled_frames_24khz": len(sample24),
        "rms": round(rms, 8),
        "rms_dbfs": round(20 * math.log10(rms), 2) if rms else None,
        "peak": round(peak, 8),
        "clipped_fraction": round(clipped, 8),
        "noise_floor_rms": round(floor, 8),
        "vad_threshold_rms": round(threshold, 8),
        "active_blocks_20ms": len(active),
        "capture_edge_activity": False,
        "quality_issues": issues,
    }
    if len(active) < 3:
        issues.append("NO_SPEECH_ACTIVITY")
        sample24.fill(0)
        return None, diagnostics
    first, last = int(active[0]) * block, (int(active[-1]) + 1) * block
    edge = first == 0 or last >= complete * block
    if edge:
        issues.append("CAPTURE_EDGE_ACTIVITY")
    begin, end = max(0, first - 9600), min(len(sample24), last + 9600)
    diagnostics.update(
        activity_start_ms=first / 24,
        activity_end_ms=last / 24,
        trim_start_ms=begin / 24,
        trim_end_ms=end / 24,
        leading_context_ms=(first - begin) / 24,
        trailing_context_ms=(end - last) / 24,
        capture_edge_activity=edge,
        activity_to_floor_db=(
            round(20 * math.log10(float(np.mean(energy[active])) / floor), 2) if floor > 0 else None
        ),
    )
    trimmed = sample24[begin:end].copy()
    sample24.fill(0)
    if not 2400 <= len(trimmed) <= 72000:
        issues.append("INVALID_SEGMENT_LENGTH")
        trimmed.fill(0)
        return None, diagnostics
    return trimmed, diagnostics
