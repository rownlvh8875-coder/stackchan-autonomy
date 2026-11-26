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
MAX_STARTUP_PREFIX = 512


class Op(IntEnum):
    DEVICE_HELLO = 1
    PC_HELLO = 2
    SEALED = 3
    DISPLAY_READY = 4
    PENDING_TOUCH = 5
    COMPLETED = 6
    DENIED = 7
    STOP = 8
    LOCAL_SETUP_FAULT = 9


_SETUP_FAILURES = {
    1: "device_clock_invalid",
    2: "device_clock_backwards",
    3: "device_sample_gap",
    4: "device_sensor_read",
    5: "device_head_input",
    6: "device_usb_start",
    7: "device_pairing_display",
}


@dataclass(frozen=True)
class Frame:
    op: Op
    payload: bytes = b""


class SerialLike(Protocol):
    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int | None: ...


class ScpsWireError(ValueError):
    diagnostic = "setup_rejected"


class ScpsResponseTimeout(ScpsWireError):
    diagnostic = "response_timeout"


class ScpsInvalidFrame(ScpsWireError):
    def __init__(self, message: str, *, diagnostic: str = "invalid_frame"):
        self.diagnostic = diagnostic
        super().__init__(message)


class ScpsDeviceDenied(ScpsWireError):
    diagnostic = "device_denied"


class ScpsLocalSetupFailure(ScpsWireError):
    def __init__(self, code: int):
        self.diagnostic = _SETUP_FAILURES[code]
        super().__init__("device stopped before credential setup")


def _length_allowed(op: Op, length: int) -> bool:
    if op in (Op.DEVICE_HELLO, Op.PC_HELLO):
        return length == 86
    if op is Op.SEALED:
        return 35 <= length <= MAX_SEALED
    if op is Op.LOCAL_SETUP_FAULT:
        return length == 1
    return length == 0


def _check_setup_failure_code(op: Op, payload: bytes) -> None:
    if op is Op.LOCAL_SETUP_FAULT and payload[0] not in _SETUP_FAILURES:
        raise ScpsInvalidFrame("invalid local setup fault code")


def encode(frame: Frame) -> bytes:
    if not _length_allowed(frame.op, len(frame.payload)):
        raise ScpsWireError("invalid frame size")
    _check_setup_failure_code(frame.op, frame.payload)
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
    payload = wire[8:-4]
    _check_setup_failure_code(op, payload)
    return Frame(op, payload)


def _read_exact(port: SerialLike, length: int, expires_at: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        if time.monotonic() >= expires_at:
            raise ScpsResponseTimeout("USB read deadline expired")
        part = port.read(min(96, length - len(chunks)))
        if not isinstance(part, bytes) or len(part) > length - len(chunks):
            raise ScpsInvalidFrame("invalid serial read")
        chunks.extend(part)
    return bytes(chunks)


def _read_setup_header(port: SerialLike, cutoff: float) -> bytes:
    # A port opened just after boot may already contain unrelated bytes. Sync
    # once before any SCPS traffic and keep the original absolute deadline.
    matched = 0
    for seen in range(MAX_STARTUP_PREFIX + len(MAGIC)):
        try:
            octet = _read_exact(port, 1, cutoff)[0]
        except ScpsResponseTimeout as exc:
            if seen:
                raise ScpsInvalidFrame(
                    "startup data without an initial frame", diagnostic="startup_without_frame"
                ) from exc
            raise
        if octet == MAGIC[matched]:
            matched += 1
            if matched == len(MAGIC):
                return MAGIC + _read_exact(port, HEADER_BYTES - len(MAGIC), cutoff)
        else:
            matched = int(octet == MAGIC[0])
    raise ScpsInvalidFrame(
        "startup data exceeded initial frame prefix limit", diagnostic="startup_prefix_limit"
    )


def read_one(
    port: SerialLike, deadline_seconds: float = 20.0, *, first_setup_frame: bool = False
) -> Frame:
    if not 0 < deadline_seconds <= 135.0:
        raise ScpsWireError("invalid read deadline")
    cutoff = time.monotonic() + deadline_seconds
    header = (
        _read_setup_header(port, cutoff)
        if first_setup_frame
        else _read_exact(port, HEADER_BYTES, cutoff)
    )
    if header[:4] != MAGIC or header[4] != VERSION or not 1 <= header[5] <= Op.LOCAL_SETUP_FAULT:
        raise ScpsInvalidFrame("invalid framing header", diagnostic="invalid_header")
    op = Op(header[5])
    payload_size = int.from_bytes(header[6:], "little")
    if not _length_allowed(op, payload_size):
        raise ScpsInvalidFrame("invalid declared length", diagnostic="invalid_length")
    trailer = _read_exact(port, payload_size + CRC_BYTES, cutoff)
    try:
        return decode(header + trailer)
    except ScpsWireError as exc:
        raise ScpsInvalidFrame("invalid frame body", diagnostic="invalid_body") from exc


def write_one(port: SerialLike, frame: Frame) -> None:
    wire = encode(frame)
    count = port.write(wire)
    # Reject partial write rather than repeating a possibly delivered secret.
    if count != len(wire):
        raise ScpsWireError("USB output incomplete; do not retry")


def expect(port: SerialLike, expected: Op, seconds: float) -> Frame:
    frame = read_one(port, seconds, first_setup_frame=expected is Op.DEVICE_HELLO)
    if frame.op is Op.DENIED:
        raise ScpsDeviceDenied("unexpected pairing state")
    if frame.op is Op.LOCAL_SETUP_FAULT:
        if expected in (Op.DEVICE_HELLO, Op.DISPLAY_READY):
            raise ScpsLocalSetupFailure(frame.payload[0])
        raise ScpsInvalidFrame("local setup fault outside initial exchange")
    if frame.op != expected:
        raise ScpsWireError("unexpected pairing state")
    return frame
