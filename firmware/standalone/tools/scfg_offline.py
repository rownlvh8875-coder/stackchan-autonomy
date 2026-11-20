"""Build and inspect offline SCFG wake-feature enrollment bundles.

No serial/device, microphone, network, API, or flash access is implemented.
Only validated SWK1 quantized features are accepted; raw PCM is rejected.
"""

import argparse
import os
import secrets
import struct
import zlib
from pathlib import Path

FEATURE_BYTES = 64 * 13
PROFILE_MAX_BYTES = 11 + 3 * FEATURE_BYTES
FRAME_MAX_PAYLOAD = 8192
DEFAULT_CHUNK = 1024
HEADER = struct.Struct("<4sBBHIH")
ACK = struct.Struct("<4sBBBBIH")


class ProtocolError(ValueError):
    """Invalid, incomplete, or unsupported feature enrollment packet."""


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def validate_profile(profile: bytes) -> int:
    """Return template count; never accepts raw audio or unversioned templates."""
    if len(profile) < 11 or len(profile) > PROFILE_MAX_BYTES:
        raise ProtocolError("profile length invalid")
    if profile[:4] != b"SWK1":
        raise ProtocolError("feature profile version/magic invalid")
    count = profile[4]
    if count not in (1, 2, 3) or len(profile) != 11 + count * FEATURE_BYTES:
        raise ProtocolError("feature template count/length invalid")
    if int.from_bytes(profile[5:7], "little") == 0:
        raise ProtocolError("missing calibration threshold")
    if crc32(profile[:-4]) != int.from_bytes(profile[-4:], "little"):
        raise ProtocolError("feature CRC invalid")
    return count


def encode_frame(op: int, nonce: int, seq: int, payload: bytes) -> bytes:
    if op not in (4, 5, 6) or not 0 < nonce < 2**32 or not 0 <= seq < 65536:
        raise ProtocolError("unsupported operation or nonce/sequence")
    if len(payload) > FRAME_MAX_PAYLOAD:
        raise ProtocolError("frame too large")
    frame = HEADER.pack(b"SCFG", 1, op, len(payload), nonce, seq) + payload
    return frame + struct.pack("<I", crc32(frame))


def make_bundle(profile: bytes, nonce: int, chunk_size: int = DEFAULT_CHUNK) -> bytes:
    validate_profile(profile)
    if not 1 <= chunk_size <= 4096:
        raise ProtocolError("chunk size outside feature transport bounds")
    begin = struct.pack("<HI", len(profile), crc32(profile))
    out = bytearray(encode_frame(4, nonce, 0, begin))
    chunks = [profile[i : i + chunk_size] for i in range(0, len(profile), chunk_size)]
    for seq, data in enumerate(chunks):
        out.extend(encode_frame(5, nonce, seq, data))
    out.extend(encode_frame(6, nonce, len(chunks), b""))
    return bytes(out)


def verify_bundle(bundle: bytes) -> tuple[int, int]:
    """Verify a complete offline transaction; return nonce and chunk count."""
    frames = []
    offset = 0
    while offset < len(bundle):
        if len(bundle) - offset < 18:
            raise ProtocolError("truncated frame")
        magic, version, op, size, nonce, seq = HEADER.unpack_from(bundle, offset)
        end = offset + 18 + size
        if magic != b"SCFG" or version != 1 or end > len(bundle) or size > 4096:
            raise ProtocolError("invalid frame boundary")
        data = bundle[offset:end]
        if crc32(data[:-4]) != int.from_bytes(data[-4:], "little"):
            raise ProtocolError("frame CRC invalid")
        frames.append((op, nonce, seq, data[14:-4]))
        offset = end
    if len(frames) < 3 or frames[0][0] != 4 or frames[0][2] != 0:
        raise ProtocolError("missing BEGIN")
    if frames[-1][0] != 6 or frames[-1][3] or len(frames[0][3]) != 6:
        raise ProtocolError("missing COMMIT")
    nonce = frames[0][1]
    chunks = frames[1:-1]
    if len(chunks) > 4096 or frames[-1][1] != nonce or frames[-1][2] != len(chunks):
        raise ProtocolError("transaction sequence invalid")
    for i, (op, n, seq, payload) in enumerate(chunks):
        if op != 5 or n != nonce or seq != i or not payload or len(payload) > 4096:
            raise ProtocolError("feature chunk order invalid")
    profile = b"".join(item[3] for item in chunks)
    expected_length, expected_crc = struct.unpack("<HI", frames[0][3])
    if len(profile) != expected_length or crc32(profile) != expected_crc:
        raise ProtocolError("transaction checksum/length invalid")
    validate_profile(profile)
    return nonce, len(chunks)


def decode_ack(ack: bytes) -> tuple[int, int, int, int, int]:
    if len(ack) != 18 or crc32(ack[:-4]) != int.from_bytes(ack[-4:], "little"):
        raise ProtocolError("invalid SACK length/CRC")
    magic, version, op, code, state, nonce, seq = ACK.unpack_from(ack)
    if magic != b"SACK" or version != 1 or not 1 <= op <= 7:
        raise ProtocolError("invalid SACK header")
    if code > 6 or state > 11:
        raise ProtocolError("invalid SACK status")
    return op, code, state, nonce, seq


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="Private, validated SWK1 feature blob")
    parser.add_argument("--output", type=Path, help="Local bundle (never transmitted)")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK)
    args = parser.parse_args()
    try:
        with args.profile.open("rb") as source:
            profile = source.read(PROFILE_MAX_BYTES + 1)
        count = validate_profile(profile)
        if args.output is not None:
            nonce = secrets.randbelow(2**32 - 1) + 1
            wire = make_bundle(profile, nonce, args.chunk_size)
            verify_bundle(wire)
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(args.output, flags, 0o600)
            with os.fdopen(fd, "wb") as dest:
                dest.write(wire)
            print(f"Offline bundle written: {len(wire)} bytes, {count} templates")
        else:
            print(f"Feature profile validated: {count} templates; no device accessed")
    except (OSError, ProtocolError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
