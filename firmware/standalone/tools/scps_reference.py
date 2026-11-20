"""Offline reference for K151 Secure PC Setup v1 (SCPS).

Requires the externally installed ``cryptography`` package. This is *not* a
serial/USB application and must not be treated as a production credential
provisioning tool. No real credentials or private keys are written to disk.

Security: P-256 ephemeral ECDH + HKDF-SHA256 + AES-256-GCM. The ECDH public
keys are unauthenticated until the human *visually compares* the eight-digit
SAS on the physical device and PC. If the display/input path is compromised,
manual SAS verification cannot establish authenticity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

DEVICE_MAGIC: Final = b"KSD1"
PC_MAGIC: Final = b"KSP1"
SEALED_MAGIC: Final = b"KSE1"
PAYLOAD_MAGIC: Final = b"KSC1"
VERSION: Final = 1
HELLO_SIZE: Final = 4 + 1 + 65 + 16
SEALED_HEADER_SIZE: Final = 4 + 1 + 12 + 2
MAX_PAYLOAD: Final = 4 + 1 + 3 + 32 + 64 + 220
KEY_INFO: Final = b"K151-SCPS-v1/aes256gcm/"
SAS_INFO: Final = b"K151-SCPS-v1/sas/"


def _parse_hello(data: bytes, magic: bytes) -> tuple[ec.EllipticCurvePublicKey, bytes]:
    if len(data) != HELLO_SIZE or data[:4] != magic or data[4] != VERSION:
        raise ValueError("invalid or truncated pairing hello")
    point, nonce = data[5:70], data[70:86]
    if point[0] != 0x04 or nonce == bytes(16):
        raise ValueError("invalid public point or nonce")
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    return pub, nonce


def _hello(key: ec.EllipticCurvePrivateKey, nonce: bytes, magic: bytes) -> bytes:
    if len(nonce) != 16 or nonce == bytes(16):
        raise ValueError("invalid nonce")
    point = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    assert len(point) == 65
    return magic + bytes([VERSION]) + point + nonce


def _derived(shared: bytes, device_hello: bytes, pc_hello: bytes, label: bytes, n: int) -> bytes:
    # Fixed transcript order: device then PC, independent of initiator.
    _, dev_nonce = _parse_hello(device_hello, DEVICE_MAGIC)
    _, pc_nonce = _parse_hello(pc_hello, PC_MAGIC)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=n,
        salt=dev_nonce + pc_nonce,
        info=label + device_hello[5:70] + pc_hello[5:70],
    ).derive(shared)


def _sas(shared: bytes, device_hello: bytes, pc_hello: bytes) -> str:
    data = _derived(shared, device_hello, pc_hello, SAS_INFO, 8)
    return f"{int.from_bytes(data, 'big') % 100_000_000:08d}"


def _encode_credentials(ssid: bytes, password: str, api_key: str) -> bytes:
    if not 1 <= len(ssid) <= 32 or any(b < 0x20 or b == 0x7F for b in ssid):
        raise ValueError("invalid SSID")
    if not 8 <= len(password) <= 64 or any(ord(c) < 0x20 or ord(c) > 0x7E for c in password):
        raise ValueError("invalid Wi-Fi passphrase")
    if len(password) == 64 and any(c not in "0123456789abcdefABCDEF" for c in password):
        raise ValueError("64-character Wi-Fi PSK must be hex")
    if not 16 <= len(api_key) <= 220 or any(ord(c) <= 0x20 or ord(c) >= 0x7F for c in api_key):
        raise ValueError("invalid API key")
    key_bytes, pass_bytes = api_key.encode("ascii"), password.encode("ascii")
    return (
        PAYLOAD_MAGIC
        + bytes([VERSION, len(ssid), len(pass_bytes), len(key_bytes)])
        + ssid
        + pass_bytes
        + key_bytes
    )


@dataclass(frozen=True, repr=False)
class FakeCredentials:
    """Offline-only test representation; Python strings cannot be reliably zeroed."""

    ssid: bytes
    password: str
    api_key: str


class PcSession:
    """Ephemeral PC role: no serial, no persisted keys, no unattended pairing."""

    def __init__(self, device_hello: bytes):
        device_pub, _ = _parse_hello(device_hello, DEVICE_MAGIC)
        self._key = ec.generate_private_key(ec.SECP256R1())
        self.device_hello = device_hello
        self.pc_hello = _hello(self._key, os.urandom(16), PC_MAGIC)
        self._shared = self._key.exchange(ec.ECDH(), device_pub)
        self.sas = _sas(self._shared, self.device_hello, self.pc_hello)
        self._used = False

    def seal(
        self,
        ssid: bytes,
        password: str,
        api_key: str,
        code_read_from_device_display: str,
        reviewed_locally: bool,
    ) -> bytes:
        if self._used or not reviewed_locally or code_read_from_device_display != self.sas:
            raise ValueError("manual device display SAS verification missing")
        payload = _encode_credentials(ssid, password, api_key)
        self._used = True  # One attempt, even if AES-GCM construction fails.
        key = _derived(self._shared, self.device_hello, self.pc_hello, KEY_INFO, 32)
        iv = os.urandom(12)
        encrypted_length = len(payload) + 16
        header = SEALED_MAGIC + bytes([VERSION]) + iv + encrypted_length.to_bytes(2, "little")
        ciphertext = AESGCM(key).encrypt(iv, payload, self.device_hello + self.pc_hello + header)
        self._shared = b""
        self._key = None  # Key objects/immutable bytes can persist in Python-managed memory.
        assert len(ciphertext) == encrypted_length
        return header + ciphertext


class OfflineDeviceEmulator:
    """Pure PC fixture. NOT a trusted device or a replacement for K151 firmware."""

    def __init__(self):
        self._key = ec.generate_private_key(ec.SECP256R1())
        self.device_hello = _hello(self._key, os.urandom(16), DEVICE_MAGIC)
        self.pc_hello: bytes | None = None
        self._shared: bytes | None = None
        self._consumed = False
        self._stopped = False

    def accept_pc_hello(self, pc_hello: bytes, owner_window: bool) -> str:
        if not owner_window or self._stopped or self._consumed or self.pc_hello is not None:
            raise ValueError("one-time physical presence required")
        pc_public, _ = _parse_hello(pc_hello, PC_MAGIC)
        self._shared = self._key.exchange(ec.ECDH(), pc_public)
        self.pc_hello = pc_hello
        return _sas(self._shared, self.device_hello, pc_hello)

    def open_sealed(
        self,
        packet: bytes,
        local_sas_approved: bool,
        owner_window: bool,
        physical_stop: bool = False,
    ) -> FakeCredentials:
        if (
            self._stopped
            or physical_stop
            or not owner_window
            or not local_sas_approved
            or self._consumed
        ):
            self.stop()
            raise ValueError("trusted local SAS/physical presence required")
        if self.pc_hello is None or self._shared is None:
            self.stop()
            raise ValueError("no authenticated pairing handshake")
        self._consumed = True  # Never accept a second GCM ciphertext in this session.
        if (
            len(packet) < SEALED_HEADER_SIZE + 16
            or packet[:4] != SEALED_MAGIC
            or packet[4] != VERSION
        ):
            raise ValueError("invalid sealed envelope")
        iv = packet[5:17]
        if iv == bytes(12):
            raise ValueError("unsafe zero GCM IV")
        length = int.from_bytes(packet[17:19], "little")
        if not 16 < length <= MAX_PAYLOAD + 16 or len(packet) != SEALED_HEADER_SIZE + length:
            raise ValueError("invalid encrypted payload length")
        key = _derived(self._shared, self.device_hello, self.pc_hello, KEY_INFO, 32)
        try:
            plaintext = AESGCM(key).decrypt(
                iv,
                packet[SEALED_HEADER_SIZE:],
                self.device_hello + self.pc_hello + packet[:SEALED_HEADER_SIZE],
            )
        except InvalidTag as exc:
            raise ValueError("AEAD authentication failed") from exc
        if len(plaintext) < 8 or plaintext[:4] != PAYLOAD_MAGIC or plaintext[4] != VERSION:
            raise ValueError("bad payload format")
        ssid_len, pass_len, key_len = plaintext[5:8]
        if len(plaintext) != 8 + ssid_len + pass_len + key_len:
            raise ValueError("malformed payload length")
        ssid = plaintext[8 : 8 + ssid_len]
        pw = plaintext[8 + ssid_len : 8 + ssid_len + pass_len].decode("ascii")
        token = plaintext[8 + ssid_len + pass_len :].decode("ascii")
        if _encode_credentials(ssid, pw, token) != plaintext:
            raise ValueError("invalid credentials")
        return FakeCredentials(ssid, pw, token)

    def stop(self) -> None:
        self._stopped = True
        self._shared = None
        self._key = None  # Python does not promise immediate memory erasure.
