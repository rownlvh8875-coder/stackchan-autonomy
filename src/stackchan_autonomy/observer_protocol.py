"""SCOB v1: bounded wire decoding and source-checked, RAM-only observations."""

import hashlib
import io
import json
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

UPSTREAM = "28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400"
_HEADER = struct.Struct("!4sBBH16sII")
_KINDS = {1, 2, 3, 0x81, 0x82, 0x83, 0x84, 0xFF}
_LIMITS = {1: 0, 2: 16, 3: 16, 0x84: 131072}


class ObserverError(Exception):
    def __init__(self, code="PC_OBSERVER_UNAVAILABLE"):
        allowed = {
            "PC_OBSERVER_UNAVAILABLE",
            "PC_OBSERVER_PROTOCOL_FAILED",
            "PC_OBSERVER_PAIRING_REQUIRED",
            "PC_OBSERVER_IDENTITY_CHANGED",
            "PC_OBSERVER_BUSY",
            "PC_OBSERVER_CONSENT_REQUIRED",
        }
        self.code = code if code in allowed else "PC_OBSERVER_UNAVAILABLE"
        super().__init__(self.code)


def encode_frame(kind: int, nonce: bytes, payload: bytes = b"") -> bytes:
    if kind not in _KINDS or len(nonce) != 16 or len(payload) > _LIMITS.get(kind, 4096):
        raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
    prefix = struct.pack("!4sBBH16sI", b"SCOB", 1, kind, 0, nonce, len(payload))
    return prefix + struct.pack("!I", zlib.crc32(prefix + payload)) + payload


class FrameReader:
    def __init__(self):
        self.buffer = bytearray()
        self.noise = 0

    def feed(self, data: bytes):
        if len(data) > 4096:
            raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
        self.buffer.extend(data)
        return self.pop()

    def pop(self):
        b = self.buffer
        while len(b) >= 4 and b[:4] != b"SCOB":
            at = b.find(b"SCOB", 1)
            discard = at if at >= 0 else len(b) - 3
            self.noise += discard
            del b[:discard]
            if self.noise + (len(b) if at < 0 else 0) > 1024 * 1024:
                raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
        if len(b) < 32:
            return None
        _, version, kind, flags, nonce, size, crc = _HEADER.unpack(b[:32])
        if version != 1 or flags or kind not in _KINDS or size > _LIMITS.get(kind, 4096):
            raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
        if len(b) < 32 + size:
            return None
        payload = bytes(b[32 : 32 + size])
        if zlib.crc32(bytes(b[:28]) + payload) != crc:
            raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
        del b[: 32 + size]
        return kind, nonce, payload


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def exact_assertion_types(cls, value):
        if isinstance(value, dict):
            for name, required in (
                ("contract_version", int),
                ("read_only", bool),
                ("pose_verified", bool),
            ):
                if name in value and type(value[name]) is not required:
                    raise ValueError("invalid contract assertion")
        return value


class Hello(StrictModel):
    contract_version: Literal[1]
    firmware: Literal["unofficial-observer-prototype"]
    upstream: Literal[UPSTREAM]
    read_only: Literal[True]
    device_id: str = Field(pattern=r"^[0-9a-f]{12}$", repr=False)
    boot_id: str = Field(pattern=r"^[0-9a-f]{32}$", repr=False)
    capabilities: list[Literal["status", "snapshot"]] = Field(min_length=2, max_length=2)


class Touch(StrictModel):
    kind: int = Field(ge=0, le=4)
    age_ms: int = Field(ge=0, le=2**63 - 1)
    provenance: Literal["hal_head_pet_event"]


class Motion(StrictModel):
    kind: int = Field(ge=0, le=2)
    age_ms: int = Field(ge=0, le=2**63 - 1)
    provenance: Literal["hal_imu_motion_event"]


class Status(StrictModel):
    boot_id: str = Field(pattern=r"^[0-9a-f]{32}$", repr=False)
    uptime_ms: int = Field(ge=0, le=2**63 - 1)
    touch: Touch | None
    imu: Motion | None
    head_pose: None
    pose_verified: Literal[False]


class Snapshot(Status):
    image_id: str = Field(pattern=r"^[0-9a-f]{32}$", repr=False)
    captured_ms: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(ge=1, le=640)
    height: int = Field(ge=1, le=640)
    byte_count: int = Field(ge=1, le=131072)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)


def parse_json(model, payload):
    try:
        # Reject duplicate keys rather than letting a later value replace source identity.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        return model.model_validate(json.loads(payload, object_pairs_hook=unique))
    except (ValueError, TypeError, ValidationError, UnicodeError, RecursionError):
        raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED") from None


@dataclass(frozen=True, repr=False, init=False)
class VerifiedObservation:
    jpeg: bytes = field(repr=False)
    metadata: Snapshot = field(repr=False)
    received_at: float = field(repr=False)
    _expected_nonce: bytes = field(repr=False)
    _expected_boot: str = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")

    @classmethod
    def validate(cls, jpeg, metadata, *, nonce, boot_id, received_at=None):
        try:
            if (
                metadata.boot_id != boot_id
                or metadata.image_id != nonce.hex()
                or len(jpeg) != metadata.byte_count
                or hashlib.sha256(jpeg).hexdigest() != metadata.sha256
                or not 0 <= metadata.uptime_ms - metadata.captured_ms <= 2000
                or metadata.width * metadata.height > 307200
            ):
                raise ValueError
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != "JPEG" or image.size != (metadata.width, metadata.height):
                    raise ValueError
                image.verify()
            with Image.open(io.BytesIO(jpeg)) as image:
                image.load()
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED") from None
        result = object.__new__(cls)
        for name, value in (
            ("jpeg", jpeg),
            ("metadata", metadata),
            ("received_at", time.monotonic() if received_at is None else received_at),
            ("_expected_nonce", nonce),
            ("_expected_boot", boot_id),
        ):
            object.__setattr__(result, name, value)
        return result

    def age_ms(self):
        age = (time.monotonic() - self.received_at) * 1000
        if not 0 <= age <= 10000:
            raise ObserverError("PC_OBSERVER_UNAVAILABLE")
        return int(age) + self.metadata.uptime_ms - self.metadata.captured_ms

    def recheck(self):
        self.age_ms()
        self.validate(
            self.jpeg,
            self.metadata,
            nonce=self._expected_nonce,
            boot_id=self._expected_boot,
            received_at=self.received_at,
        )

    def public_metadata(self):
        return {
            "source": "usb_observer_prototype",
            "capture_age_ms": self.age_ms(),
            "touch": self.metadata.touch.model_dump() if self.metadata.touch else None,
            "imu": self.metadata.imu.model_dump() if self.metadata.imu else None,
            "head_pose": None,
            "pose_verified": False,
        }

    def upload_jpeg(self):
        self.recheck()
        # New pixels-only image: no EXIF, comments, ICC or bytes after EOI.
        with Image.open(io.BytesIO(self.jpeg)) as decoded:
            rgb = decoded.convert("RGB")
            clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())
        try:
            for quality in (85, 60, 35, 15):
                stream = io.BytesIO()
                clean.save(stream, format="JPEG", quality=quality)
                wire = stream.getvalue()
                if len(wire) <= 131072:
                    return wire
        finally:
            clean.close()
            rgb.close()
        raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
