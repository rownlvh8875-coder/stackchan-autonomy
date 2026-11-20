"""Real arithmetic/format/device boundary tests; synthetic signals, no live audio."""

import importlib.util
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


@pytest.fixture
def audio():
    spec = importlib.util.spec_from_file_location("pc_mic_audio", TOOLS / "pc_mic_audio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def np():
    return pytest.importorskip("numpy")


def utterance(np, frequency=800):
    samples = np.zeros(120000, dtype=np.int16)
    t = np.arange(24000) / 48000
    samples[24000:48000] = np.rint(4000 * np.sin(2 * np.pi * frequency * t)).astype(np.int16)
    return samples


def test_diagnostics_separate_input_activity_and_preserved_context(audio, np):
    signal = utterance(np)
    trimmed, d = audio.analyze_48k(signal, np)
    assert len(trimmed) == 31200  # 0.5s voice + 0.4s on each side, at24k.
    assert d["input_frames_48khz"] == 120000 and d["resampled_frames_24khz"] == 60000
    assert d["activity_start_ms"] == 500 and d["activity_end_ms"] == 1000
    assert d["trim_start_ms"] == 100 and d["trim_end_ms"] == 1400
    assert d["leading_context_ms"] == 400 and d["trailing_context_ms"] == 400
    assert not d["capture_edge_activity"] and d["quality_issues"] == []
    assert 0.12 < d["peak"] < 0.123 and 0 < d["rms"] < d["peak"]
    assert d["clipped_fraction"] == 0


def test_silence_reports_quality_without_a_candidate(audio, np):
    trimmed, d = audio.analyze_48k(np.zeros(120000, dtype=np.int16), np)
    assert trimmed is None and d["quality_issues"] == ["NO_SPEECH_ACTIVITY"]
    assert d["rms"] == 0 and d["peak"] == 0


@pytest.mark.parametrize("edge", ["start", "end"])
def test_activity_at_capture_edge_is_risk_not_claimed_truncation(audio, np, edge):
    signal = np.zeros(120000, dtype=np.int16)
    tone = np.rint(4000 * np.sin(2 * np.pi * 800 * np.arange(24000) / 48000)).astype(np.int16)
    signal[:24000] = tone if edge == "start" else 0
    if edge == "end":
        signal[-24000:] = tone
    trimmed, d = audio.analyze_48k(signal, np)
    assert trimmed is not None and d["capture_edge_activity"]
    assert "CAPTURE_EDGE_ACTIVITY" in d["quality_issues"]


def test_raw_clipping_is_reported_even_if_filter_reduces_peak(audio, np):
    signal = utterance(np)
    signal[25000:25150] = 32767
    _, d = audio.analyze_48k(signal, np)
    assert d["clipped_fraction"] >= 0.001 and "CLIPPING" in d["quality_issues"]


def test_fir_keeps_length_and_rejects_out_of_band_alias(audio, np):
    low, _ = audio.analyze_48k(utterance(np, 1000), np)
    high, d = audio.analyze_48k(utterance(np, 18000), np)
    assert d["resampled_frames_24khz"] == 60000
    # Independent physical criterion: >35dB suppression of a tone above new Nyquist.
    assert (
        high is None
        or np.sqrt(np.mean(high.astype(float) ** 2))
        < np.sqrt(np.mean(low.astype(float) ** 2)) * 0.018
    )


@pytest.mark.parametrize("bad", ["float", "stereo", "short", "long"])
def test_invalid_capture_format_is_rejected(audio, np, bad):
    signal = {
        "float": np.zeros(12000),
        "stereo": np.zeros((12000, 2), dtype=np.int16),
        "short": np.zeros(4799, dtype=np.int16),
        "long": np.zeros(144001, dtype=np.int16),
    }[bad]
    with pytest.raises(audio.AudioError):
        audio.analyze_48k(signal, np)


def test_device_fingerprint_detects_changed_device_at_same_index(audio):
    class Devices:
        name = "Microphone A"

        def query_devices(self, index, kind):
            assert index == 9 and kind == "input"
            return {
                "name": self.name,
                "hostapi": 0,
                "max_input_channels": 2,
                "default_samplerate": 48000.0,
            }

        def query_hostapis(self, index):
            return {"name": "Windows WASAPI"}

    sd = Devices()
    first = audio.device_identity(sd, 9)
    assert first == audio.device_identity(sd, 9)
    sd.name = "Microphone B"
    with pytest.raises(audio.AudioError, match="input_device_changed"):
        audio.require_device(sd, 9, first)
