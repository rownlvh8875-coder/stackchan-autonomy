"""Explicitly paired, one-request-at-a-time USB client. No media persistence or retries."""

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from .observer_protocol import (
    FrameReader,
    Hello,
    ObserverError,
    Snapshot,
    Status,
    VerifiedObservation,
    encode_frame,
    parse_json,
)

DEFAULT_PROFILE = Path(".local/observer/profile.json")


def load_profile(path):
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(1025)
        value = json.loads(data)
        if len(data) > 1024 or set(value) != {"device_id"}:
            raise ValueError
        device = value["device_id"]
        if not isinstance(device, str) or not re.fullmatch("[0-9a-f]{12}", device):
            raise ValueError
        return device
    except (OSError, ValueError, TypeError):
        raise ObserverError("PC_OBSERVER_PAIRING_REQUIRED") from None


def save_profile(path, device_id):
    if not re.fullmatch("[0-9a-f]{12}", device_id):
        raise ObserverError("PC_OBSERVER_PAIRING_REQUIRED")
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"device_id": device_id}, stream)
    except OSError:
        raise ObserverError("PC_OBSERVER_PAIRING_REQUIRED") from None


def open_serial(port):
    import serial

    if not isinstance(port, str) or not port or len(port) > 256 or "://" in port:
        raise ObserverError()
    link = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=0.5)
    link.dtr = False
    link.rts = False
    link.port = port
    try:
        link.open()
    except Exception:
        link.close()
        raise ObserverError() from None
    return link


class ObserverClient:
    def __init__(
        self,
        port,
        profile=DEFAULT_PROFILE,
        *,
        timeout_s=10,
        transport_factory=open_serial,
        pairing=False,
    ):
        if not 1 <= timeout_s <= 30:
            raise ObserverError()
        self.port, self.profile = port, profile
        self.timeout_s, self.factory, self.pairing = timeout_s, transport_factory, pairing
        self.link = None
        self.hello = None
        self.reader = FrameReader()
        self.lock = threading.Lock()

    def __enter__(self):
        self.close()  # Explicit reopen always starts a fresh handshake.
        try:
            expected = None if self.pairing else load_profile(self.profile)
            self.link = self.factory(self.port)
            nonce, payload = self._request(1, b"", 0x81)
            self.hello = parse_json(Hello, payload)
            if set(self.hello.capabilities) != {"status", "snapshot"}:
                raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
            if expected is not None and self.hello.device_id != expected:
                raise ObserverError("PC_OBSERVER_IDENTITY_CHANGED")
            return self
        except ObserverError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ObserverError() from None

    def __exit__(self, *args):
        self.close()

    def close(self):
        link, self.link = self.link, None
        self.hello = None
        self.reader = FrameReader()
        if link:
            try:
                link.close()
            except Exception:
                pass

    def _receive(self, expected, nonce, deadline):
        while time.monotonic() < deadline:
            frame = self.reader.pop()
            if frame is None:
                frame = self.reader.feed(self.link.read(4096))
            if frame is None:
                continue
            kind, received_nonce, payload = frame
            if received_nonce != nonce:
                raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
            if kind == 0xFF:
                # No received error text is ever reflected across the public boundary.
                raise ObserverError(
                    "PC_OBSERVER_BUSY"
                    if payload == b'{"error":"BUSY"}'
                    else "PC_OBSERVER_UNAVAILABLE"
                )
            if kind != expected:
                raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
            return payload
        raise ObserverError()

    def _request(self, command, payload, reply):
        if self.link is None:
            raise ObserverError()
        nonce = secrets.token_bytes(16)
        deadline = time.monotonic() + self.timeout_s
        wire = encode_frame(command, nonce, payload)
        if self.link.write(wire) != len(wire):
            raise ObserverError()
        return nonce, self._receive(reply, nonce, deadline)

    def _operation(self, capture):
        if not self.lock.acquire(blocking=False):
            raise ObserverError("PC_OBSERVER_BUSY")
        try:
            if self.hello is None or self.link is None:
                raise ObserverError()
            start = time.monotonic()
            nonce, payload = self._request(
                3 if capture else 2, bytes.fromhex(self.hello.boot_id), 0x83 if capture else 0x82
            )
            result = parse_json(Snapshot if capture else Status, payload)
            if result.boot_id != self.hello.boot_id:
                raise ObserverError("PC_OBSERVER_PROTOCOL_FAILED")
            if not capture:
                return result
            jpeg = self._receive(0x84, nonce, start + self.timeout_s)
            return VerifiedObservation.validate(
                jpeg, result, nonce=nonce, boot_id=self.hello.boot_id, received_at=start
            )
        except ObserverError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ObserverError() from None
        finally:
            self.lock.release()

    def status(self):
        return self._operation(False)

    def capture(self):
        return self._operation(True)
