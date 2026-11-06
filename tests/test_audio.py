import math
import struct
from io import BytesIO

import pytest
from pydantic import ValidationError

from stackchan_autonomy.audio import PCM16Audio, from_wav, normalize_pcm, pcm_upload, to_wav
from stackchan_autonomy.opus_codec import OpusUnavailable, decode_opus, encode_opus, opus_available


def tone(rate=24000, frequency=440, duration=0.1):
    return PCM16Audio(
        pcm=b"".join(
            struct.pack("<h", round(10000 * math.sin(2 * math.pi * frequency * i / rate)))
            for i in range(round(rate * duration))
        ),
        sample_rate=rate,
        channels=1,
    )


def test_wav_roundtrip_preserves_real_format_without_logging_media():
    audio = tone()
    decoded = from_wav(to_wav(audio))
    assert decoded == audio
    assert "pcm" not in audio.model_dump()
    assert repr(audio.pcm) not in repr(audio)


@pytest.mark.parametrize(
    "data,rate,channels",
    [
        (b"", 16000, 1),
        (b"x", 16000, 1),
        (b"xx", 16000, 2),
        (b"xx", True, 1),
        (b"xx", 16000, True),
        (b"xx", 12001, 1),
        (b"xx", 16000, 3),
        (b"\0" * (16000 * 2 * 30 + 2), 16000, 1),
    ],
)
def test_bad_pcm_alignment_format_and_duration_are_rejected(data, rate, channels):
    with pytest.raises((ValidationError, ValueError)):
        PCM16Audio(pcm=data, sample_rate=rate, channels=channels)


def test_truncated_or_non_pcm_wav_is_rejected():
    import wave

    good = to_wav(tone())
    for invalid in (b"not wav", good[:-5]):
        with pytest.raises(ValueError):
            from_wav(invalid)
    stream = BytesIO()
    with wave.open(stream, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(16000)
        w.writeframes(b"\x80" * 160)
    with pytest.raises(ValueError):
        from_wav(stream.getvalue())


def test_stereo_downmix_is_little_endian_and_bounded():
    stereo = PCM16Audio(
        pcm=struct.pack("<hhhhhh", 1000, 3000, -3000, -1000, 32767, -32767),
        sample_rate=16000,
        channels=2,
    )
    mono = normalize_pcm(stereo)
    assert struct.unpack("<hhh", mono.pcm) == (2000, -2000, 0)
    assert (mono.sample_rate, mono.channels) == (16000, 1)


def test_resampling_preserves_duration_and_dc_without_clipping():
    source = PCM16Audio(pcm=struct.pack("<h", 12000) * 2400, sample_rate=24000, channels=1)
    result = normalize_pcm(source)
    assert result.frames == 1600
    assert set(struct.unpack("<1600h", result.pcm)) == {12000}
    assert normalize_pcm(result) == result


def test_downsampling_filters_above_target_nyquist_instead_of_aliasing():
    def rms(audio):
        values = struct.unpack("<" + "h" * audio.frames, audio.pcm)[50:-50]
        return math.sqrt(sum(x * x for x in values) / len(values))

    low = normalize_pcm(tone(frequency=1000))
    high = normalize_pcm(tone(frequency=10000))
    assert rms(low) > 6000
    assert rms(high) < 1000


def test_gateway_pcm_payload_uses_audited_headers_without_auth_or_file_io():
    upload = pcm_upload(normalize_pcm(tone()))
    assert upload.path == "/pcm"
    assert upload.headers == {
        "Content-Type": "application/octet-stream",
        "X-Sample-Rate": "16000",
        "X-Channels": "1",
    }
    assert len(upload.body) == 3200
    assert "body" not in repr(upload)


def test_native_opus_missing_is_an_explicit_capability_error(monkeypatch):
    from stackchan_autonomy import opus_codec

    def missing():
        raise OpusUnavailable("native codec unavailable")

    monkeypatch.setattr(opus_codec, "_library", missing)
    assert not opus_codec.opus_available()
    with pytest.raises(OpusUnavailable):
        encode_opus(normalize_pcm(tone()))


@pytest.mark.skipif(not opus_available(), reason="trusted system libopus unavailable")
def test_real_opus_roundtrip_uses_16k_mono_60ms_frames_with_padding():
    original = normalize_pcm(tone(duration=0.1))
    packets = encode_opus(original)
    assert len(packets.frames) == 2
    assert packets.original_samples == 1600
    assert packets.padded_samples == 320
    decoded = decode_opus(packets)
    assert (decoded.sample_rate, decoded.channels, decoded.frames) == (16000, 1, 1920)
    samples = struct.unpack("<1920h", decoded.pcm)
    assert max(abs(v) for v in samples[200:1400]) > 4000  # Real lossy codec, not an identity fake.


@pytest.mark.parametrize("rate", [16000.0, True, "16000", 12345])
def test_target_rate_type_is_rejected_before_resampling(rate):
    with pytest.raises(ValueError):
        normalize_pcm(tone(), rate)


@pytest.mark.parametrize("channels,length", [(1, 3), (2, 6)])
def test_wav_partial_frames_are_not_silently_truncated(channels, length):
    data = b"\0" * length
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + length)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, 16000, 16000 * channels * 2, channels * 2, 16)
        + b"data"
        + struct.pack("<I", length)
    )
    with pytest.raises(ValueError):
        from_wav(header + data)
