"""Bounded local PCM analysis. No audio IO, storage, recognition or network here."""

import hashlib
import json
import math


class AudioError(ValueError):
    pass


def descriptor_identity(sd, desc):
    api = sd.query_hostapis(desc["hostapi"])["name"]
    identity = [desc["name"], api, desc["max_input_channels"], desc["default_samplerate"]]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()


def device_identity(sd, device):
    try:
        desc = sd.query_devices(device, "input")
        if desc["max_input_channels"] < 1:
            raise AudioError("input_device_not_a_microphone")
        return descriptor_identity(sd, desc)
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
    if len(sample24) % block:
        tail = sample24[complete * block :].astype(float)
        energy = np.append(energy, np.sqrt(np.mean(tail * tail)) / 32768.0)
        tail.fill(0)
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
    first = int(active[0]) * block
    last = min(len(sample24), (int(active[-1]) + 1) * block)
    edge = first == 0 or last == len(sample24)
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


def select_microphone(device=None, choose=False):
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioError("sounddevice_not_installed") from exc
    try:
        displayed = [dict(desc) for desc in sd.query_devices()]
        identities = {
            index: descriptor_identity(sd, desc)
            for index, desc in enumerate(displayed)
            if desc["max_input_channels"] > 0
        }
        aliases = (
            "default",
            "microsoft sound mapper",
            "primary sound capture",
            "기본",
            "사운드 매퍼",
            "주 사운드 캡처",
        )
        allowed = {
            index: identity
            for index, identity in identities.items()
            if list(identities.values()).count(identity) == 1
            and not any(alias in displayed[index]["name"].casefold() for alias in aliases)
        }
        if choose:
            print(
                "노트북 입력 장치 목록 (기본 별칭/구분 불가 장치는 제외, K151 COM3는 마이크 아님):"
            )
            for index in allowed:
                desc = displayed[index]
                print(f"{index}: {desc['name']} [{sd.query_hostapis(desc['hostapi'])['name']}]")
            try:
                device = int(input("이번 실행에 사용할 입력 장치 번호: "))
            except ValueError as exc:
                raise AudioError("invalid_device_index") from exc
        if device is None or device < 0:
            raise AudioError("explicit_input_device_required")
        if device not in allowed:
            raise AudioError("ambiguous_or_default_input_device")
        identity = require_device(sd, device, allowed[device])
        print(
            json.dumps(
                {
                    "stage": "INPUT_DEVICE_SELECTED",
                    "device_index": device,
                    "device_name": displayed[device]["name"],
                },
                ensure_ascii=False,
            )
        )
        return device, identity
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError("input_device_unavailable") from exc
