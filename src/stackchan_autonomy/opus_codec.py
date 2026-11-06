"""Optional trusted system libopus. Raw 60ms packets, not Ogg or a hardware test."""

import ctypes as c
import ctypes.util
import sys
from dataclasses import dataclass, field
from functools import lru_cache

from .audio import PCM16Audio, _samples


class OpusUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _library():
    path = ctypes.util.find_library("opus")
    if not path:
        raise OpusUnavailable("trusted system libopus unavailable")
    try:
        lib = c.CDLL(path)
        lib.opus_encoder_create.argtypes = [c.c_int, c.c_int, c.c_int, c.POINTER(c.c_int)]
        lib.opus_encoder_create.restype = c.c_void_p
        lib.opus_decoder_create.argtypes = [c.c_int, c.c_int, c.POINTER(c.c_int)]
        lib.opus_decoder_create.restype = c.c_void_p
        lib.opus_encode.argtypes = [
            c.c_void_p,
            c.POINTER(c.c_int16),
            c.c_int,
            c.POINTER(c.c_ubyte),
            c.c_int32,
        ]
        lib.opus_encode.restype = c.c_int
        lib.opus_decode.argtypes = [
            c.c_void_p,
            c.POINTER(c.c_ubyte),
            c.c_int32,
            c.POINTER(c.c_int16),
            c.c_int,
            c.c_int,
        ]
        lib.opus_decode.restype = c.c_int
        lib.opus_encoder_destroy.argtypes = [c.c_void_p]
        lib.opus_encoder_destroy.restype = None
        lib.opus_decoder_destroy.argtypes = [c.c_void_p]
        lib.opus_decoder_destroy.restype = None
        return lib
    except (OSError, AttributeError):
        raise OpusUnavailable("system libopus is not compatible") from None


def opus_available():
    try:
        _library()
        return True
    except OpusUnavailable:
        return False


@dataclass(frozen=True)
class OpusFrames:
    frames: tuple[bytes, ...] = field(repr=False)
    original_samples: int
    padded_samples: int


def encode_opus(audio: PCM16Audio) -> OpusFrames:
    if (audio.sample_rate, audio.channels) != (16000, 1):
        raise ValueError("Opus requires 16kHz mono")
    lib = _library()
    error = c.c_int()
    encoder = lib.opus_encoder_create(16000, 1, 2048, c.byref(error))  # OPUS_APPLICATION_VOIP
    if error.value or not encoder:
        raise OpusUnavailable("Opus encoder initialization failed")
    packets = []
    try:
        for start in range(0, len(audio.pcm), 1920):
            chunk = audio.pcm[start : start + 1920].ljust(1920, b"\0")
            values = _samples(chunk)
            pcm = (c.c_int16 * 960)(*values)
            buffer = (c.c_ubyte * 4000)()
            size = lib.opus_encode(encoder, pcm, 960, buffer, len(buffer))
            if size <= 0:
                raise OpusUnavailable("Opus encoding failed")
            packets.append(bytes(buffer[:size]))
    finally:
        lib.opus_encoder_destroy(encoder)
    return OpusFrames(tuple(packets), audio.frames, len(packets) * 960 - audio.frames)


def decode_opus(packets: OpusFrames) -> PCM16Audio:
    if (
        not packets.frames
        or len(packets.frames) > 500
        or any(not isinstance(p, bytes) or not 0 < len(p) <= 4000 for p in packets.frames)
    ):
        raise ValueError("invalid Opus packet bounds")
    lib = _library()
    error = c.c_int()
    decoder = lib.opus_decoder_create(16000, 1, c.byref(error))
    if error.value or not decoder:
        raise OpusUnavailable("Opus decoder initialization failed")
    output = bytearray()
    try:
        for packet in packets.frames:
            data = (c.c_ubyte * len(packet)).from_buffer_copy(packet)
            pcm = (c.c_int16 * 960)()
            count = lib.opus_decode(decoder, data, len(packet), pcm, 960, 0)
            if count != 960:
                raise OpusUnavailable("invalid 60ms Opus packet")
            if sys.byteorder == "little":
                output.extend(bytes(pcm))
            else:
                import struct

                output.extend(struct.pack("<960h", *pcm))
    finally:
        lib.opus_decoder_destroy(decoder)
    return PCM16Audio(pcm=bytes(output), sample_rate=16000, channels=1)
