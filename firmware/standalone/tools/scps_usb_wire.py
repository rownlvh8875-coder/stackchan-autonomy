"""SCPS v1 USB envelopes. No secrets are ever sent via SCFG.

CRC32 detects framing accidents and is NOT authentication. An active USB
adversary is only rejected when the operator compares the physical LCD's
8-digit SAS with the PC's SAS and the device requires a second local touch.
"""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

MAGIC = b"SCPW"
VERSION = 1
HEADER_BYTES = 8
CRC_BYTES = 4
MAX_SEALED = 359
MAX_FRAME = HEADER_BYTES + MAX_SEALED + CRC_BYTES


class Op(IntEnum):
    DEVICE_HELLO = 1
    PC_HELLO = 2
    SEALED = 3
    DISPLAY_READY = 4
    PENDING_TOUCH = 5
    COMPLETED = 6
    DENIED = 7
    STOP = 8


@dataclass(frozen=True)
class Frame:
    op: Op
    payload: bytes = b""


class SerialLike(Protocol):
    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int | None: ...


class ScpsWireError(ValueError):
    pass


def _length_allowed(op: Op, length: int) -> bool:
    if op in (Op.DEVICE_HELLO, Op.PC_HELLO):
        return length == 86
    if op is Op.SEALED:
        return 35 <= length <= MAX_SEALED
    return length == 0


def encode(frame: Frame) -> bytes:
    if not _length_allowed(frame.op, len(frame.payload)):
        raise ScpsWireError("invalid frame size")
    header = MAGIC + bytes((VERSION, frame.op)) + len(frame.payload).to_bytes(2, "little")
    framed = header + frame.payload
    return framed + struct.pack("<I", zlib.crc32(framed))


def decode(wire: bytes) -> Frame:
    if len(wire) < HEADER_BYTES + CRC_BYTES or len(wire) > MAX_FRAME:
        raise ScpsWireError("truncated or oversized frame")
    if wire[:4] != MAGIC or wire[4] != VERSION:
        raise ScpsWireError("unrecognized protocol/version")
    try:
        op = Op(wire[5])
    except ValueError as exc:
        raise ScpsWireError("unrecognized opcode") from exc
    size = int.from_bytes(wire[6:8], "little")
    if not _length_allowed(op, size) or len(wire) != HEADER_BYTES + size + CRC_BYTES:
        raise ScpsWireError("invalid payload length")
    if int.from_bytes(wire[-4:], "little") != zlib.crc32(wire[:-4]):
        raise ScpsWireError("frame integrity check failed")
    return Frame(op, wire[8:-4])


def _read_exact(port: SerialLike, length: int, expires_at: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        if time.monotonic() >= expires_at:
            raise ScpsWireError("USB read deadline expired")
        part = port.read(min(96, length - len(chunks)))
        if not isinstance(part, bytes) or len(part) > length - len(chunks):
            raise ScpsWireError("invalid serial read")
        chunks.extend(part)
    return bytes(chunks)


def read_one(port: SerialLike, deadline_seconds: float = 20.0) -> Frame:
    if not 0 < deadline_seconds <= 135.0:
        raise ScpsWireError("invalid read deadline")
    cutoff = time.monotonic() + deadline_seconds
    header = _read_exact(port, HEADER_BYTES, cutoff)
    if header[:4] != MAGIC or header[4] != VERSION or not 1 <= header[5] <= 8:
        raise ScpsWireError("invalid framing header")
    op = Op(header[5])
    payload_size = int.from_bytes(header[6:], "little")
    if not _length_allowed(op, payload_size):
        raise ScpsWireError("invalid declared length")
    return decode(header + _read_exact(port, payload_size + CRC_BYTES, cutoff))


def write_one(port: SerialLike, frame: Frame) -> None:
    wire = encode(frame)
    count = port.write(wire)
    # Reject partial write rather than repeating a possibly delivered secret.
    if count != len(wire):
        raise ScpsWireError("USB output incomplete; do not retry")


def expect(port: SerialLike, expected: Op, seconds: float) -> Frame:
    frame = read_one(port, seconds)
    if frame.op != expected:
        raise ScpsWireError("unexpected pairing state")
    return frame
