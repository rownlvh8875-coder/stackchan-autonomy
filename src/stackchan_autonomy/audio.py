"""Bounded in-memory signed-16-bit LE audio. No file, microphone or speaker access."""

import array
import math
import struct
import sys
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO

from pydantic import Field, StrictInt, model_validator

from .models import StrictModel

MAX_AUDIO_BYTES = 5_760_000  # 30s, 48kHz, stereo, s16le.


class PCM16Audio(StrictModel):
    pcm: bytes = Field(
        strict=True, repr=False, exclude=True, min_length=2, max_length=MAX_AUDIO_BYTES
    )
    sample_rate: StrictInt
    channels: StrictInt

    @model_validator(mode="after")
    def valid_pcm(self):
        if self.sample_rate not in {
            8000,
            16000,
            22050,
            24000,
            32000,
            44100,
            48000,
        } or self.channels not in {1, 2}:
            raise ValueError("unsupported PCM format")
        if (
            len(self.pcm) % (self.channels * 2)
            or len(self.pcm) > self.sample_rate * self.channels * 2 * 30
        ):
            raise ValueError("PCM alignment or duration limit")
        return self

    @property
    def frames(self):
        return len(self.pcm) // (2 * self.channels)


def to_wav(audio: PCM16Audio) -> bytes:
    stream = BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(audio.channels)
        wav.setsampwidth(2)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(audio.pcm)
    return stream.getvalue()


def from_wav(data: bytes) -> PCM16Audio:
    if not isinstance(data, bytes) or len(data) > MAX_AUDIO_BYTES + 4096:
        raise ValueError("WAV size limit")
    try:
        with wave.open(BytesIO(data), "rb") as wav:
            rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
            if (
                wav.getsampwidth() != 2
                or wav.getcomptype() != "NONE"
                or channels not in {1, 2}
                or not 8000 <= rate <= 48000
                or not 0 < frames <= rate * 30
            ):
                raise ValueError("unsupported WAV format")
            # wave.getnframes floors partial PCM frames, so validate declared chunks too.
            if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise ValueError("invalid RIFF header")
            end = struct.unpack_from("<I", data, 4)[0] + 8
            if end != len(data):
                raise ValueError("incomplete RIFF envelope")
            position = 12
            data_chunks = 0
            while position + 8 <= end:
                kind = data[position : position + 4]
                size = struct.unpack_from("<I", data, position + 4)[0]
                position += 8
                if position + size > end:
                    raise ValueError("truncated RIFF chunk")
                if kind == b"data":
                    data_chunks += 1
                    if size % (channels * 2):
                        raise ValueError("incomplete PCM frame")
                position += size + (size & 1)
            if position != end or data_chunks != 1:
                raise ValueError("invalid RIFF chunks")
            pcm = wav.readframes(frames)
            if len(pcm) != frames * channels * 2:
                raise ValueError("truncated WAV")
        return PCM16Audio(pcm=pcm, sample_rate=rate, channels=channels)
    except (wave.Error, EOFError):
        raise ValueError("invalid WAV") from None


def _samples(data):
    values = array.array("h")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    return values


@lru_cache(maxsize=512)
def _kernel(phase: int, denominator: int, src_rate: int, dst_rate: int):
    fraction = phase / denominator
    cutoff = min(1.0, dst_rate / src_rate) * 0.94
    taps = []
    for offset in range(-16, 17):
        distance = offset - fraction
        sinc = (
            cutoff
            if distance == 0
            else math.sin(math.pi * cutoff * distance) / (math.pi * distance)
        )
        window = 0.5 + 0.5 * math.cos(math.pi * distance / 17)
        taps.append((offset, sinc * window))
    scale = sum(weight for _, weight in taps)
    return tuple((offset, weight / scale) for offset, weight in taps)


def normalize_pcm(audio: PCM16Audio, target_rate: int = 16000) -> PCM16Audio:
    if type(target_rate) is not int or target_rate not in {8000, 16000, 24000, 48000}:
        raise ValueError("unsupported target rate")
    source = _samples(audio.pcm)
    if audio.channels == 2:
        source = array.array(
            "h", ((source[i] + source[i + 1]) // 2 for i in range(0, len(source), 2))
        )
    if audio.sample_rate == target_rate:
        output = source
    else:
        count = max(1, round(len(source) * target_rate / audio.sample_rate))
        output = array.array("h")
        for i in range(count):
            center, phase = divmod(i * audio.sample_rate, target_rate)
            value = sum(
                source[min(len(source) - 1, max(0, center + offset))] * weight
                for offset, weight in _kernel(phase, target_rate, audio.sample_rate, target_rate)
            )
            output.append(max(-32768, min(32767, round(value))))
    if sys.byteorder != "little":
        output.byteswap()
    return PCM16Audio(pcm=output.tobytes(), sample_rate=target_rate, channels=1)


@dataclass(frozen=True)
class PCMUpload:
    path: str
    headers: dict[str, str]
    body: bytes = field(repr=False)


def pcm_upload(audio: PCM16Audio) -> PCMUpload:
    if (audio.sample_rate, audio.channels) != (16000, 1):
        raise ValueError("gateway requires normalized PCM")
    return PCMUpload(
        "/pcm",
        {"Content-Type": "application/octet-stream", "X-Sample-Rate": "16000", "X-Channels": "1"},
        audio.pcm,
    )
