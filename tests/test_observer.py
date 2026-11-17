"""Synthetic pictures and real socket byte streams; never a physical device."""

import hashlib
import io
import json
import socket
import struct
import threading
import time
import zlib

import pytest
from PIL import Image

from stackchan_autonomy.observer import ObserverClient, load_profile, save_profile
from stackchan_autonomy.observer_protocol import (
    FrameReader,
    ObserverError,
    VerifiedObservation,
    encode_frame,
)

BOOT = "11" * 16
DEVICE = "aabbccddeeff"
UPSTREAM = "28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400"


def literal(kind, nonce, payload=b"", *, version=1, flags=0, length=None):
    prefix = struct.pack(
        "!4sBBH16sI",
        b"SCOB",
        version,
        kind,
        flags,
        nonce,
        len(payload) if length is None else length,
    )
    return prefix + struct.pack("!I", zlib.crc32(prefix + payload)) + payload


def hello():
    return dict(
        contract_version=1,
        firmware="unofficial-observer-prototype",
        upstream=UPSTREAM,
        read_only=True,
        device_id=DEVICE,
        boot_id=BOOT,
        capabilities=["status", "snapshot"],
    )


def status():
    return dict(
        boot_id=BOOT, uptime_ms=1000, touch=None, imu=None, head_pose=None, pose_verified=False
    )


def picture():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "orange").save(buffer, format="JPEG")
    return buffer.getvalue()


def metadata(nonce, jpeg):
    return dict(
        **status(),
        image_id=nonce.hex(),
        captured_ms=990,
        width=16,
        height=12,
        byte_count=len(jpeg),
        sha256=hashlib.sha256(jpeg).hexdigest(),
    )


class SocketSerial:
    def __init__(self, sock):
        self.sock = sock
        sock.settimeout(0.02)
        self.closed = False

    def read(self, count):
        try:
            return self.sock.recv(min(count, 7))  # force header/payload fragmentation
        except socket.timeout:
            return b""

    def write(self, data):
        self.sock.sendall(data)
        return len(data)

    def close(self):
        self.closed = True
        self.sock.close()


def peer_client(tmp_path, *, mutate=None):
    left, right = socket.socketpair()
    transport = SocketSerial(left)
    seen = []
    errors = []

    def peer():
        try:
            right.settimeout(3)
            while True:
                data = b""
                while len(data) < 32:
                    part = right.recv(32 - len(data))
                    if not part:
                        return
                    data += part
                _, _, kind, _, nonce, size, _ = struct.unpack("!4sBBH16sII", data)
                payload = b""
                while len(payload) < size:
                    payload += right.recv(size - len(payload))
                assert data + payload == literal(kind, nonce, payload)
                seen.append((kind, nonce, payload))
                jpeg = picture()
                replies = (
                    [(0x81, hello())]
                    if kind == 1
                    else (
                        [(0x82, status())]
                        if kind == 2
                        else [(0x83, metadata(nonce, jpeg)), (0x84, jpeg)]
                    )
                )
                if mutate:
                    replies = mutate(kind, replies)
                wire = b"boot console noise\r\n" if kind == 1 else b""
                for response_kind, value in replies:
                    content = value if isinstance(value, bytes) else json.dumps(value).encode()
                    wire += literal(response_kind, nonce, content)
                right.sendall(wire)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            errors.append(error)
        finally:
            right.close()

    thread = threading.Thread(target=peer, daemon=True)
    thread.start()
    profile = tmp_path / "pair.json"
    save_profile(profile, DEVICE)
    client = ObserverClient(
        "explicit-port", profile, transport_factory=lambda port: transport, timeout_s=1
    )
    return client, seen, transport, thread, errors


def test_literal_codec_fragmentation_and_noise():
    nonce = bytes(range(16))
    packet = literal(0x82, nonce, b"{}")
    assert encode_frame(0x82, nonce, b"{}") == packet
    reader = FrameReader()
    for byte in b"console\r\n" + packet[:-1]:
        assert reader.feed(bytes([byte])) is None
    assert reader.feed(packet[-1:]) == (0x82, nonce, b"{}")


@pytest.mark.parametrize(
    "wire",
    [
        literal(0x82, bytes(16), b"{}", version=2),
        literal(0x82, bytes(16), b"{}", flags=1),
        literal(4, bytes(16)),
        literal(0x82, bytes(16), length=4097),
        literal(0x84, bytes(16), length=131073),
        literal(0x82, bytes(16), b"{}")[:-1] + b"x",
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_invalid_or_unbounded_frames_fail_closed(wire):
    with pytest.raises(ObserverError):
        reader = FrameReader()
        for offset in range(0, len(wire), 4096):
            reader.feed(wire[offset : offset + 4096])


def test_pairing_is_explicit_and_cannot_silently_replace_identity(tmp_path):
    path = tmp_path / "profile.json"
    save_profile(path, DEVICE)
    assert load_profile(path) == DEVICE
    with pytest.raises(ObserverError):
        save_profile(path, "00" * 6)
    path.write_text('{"device_id":"not-valid"}')
    with pytest.raises(ObserverError):
        load_profile(path)


def test_socket_client_handshake_status_and_verified_one_frame(tmp_path):
    client, seen, transport, thread, errors = peer_client(tmp_path)
    with client:
        assert client.status().touch is None
        observation = client.capture()
        assert isinstance(observation, VerifiedObservation)
        assert observation.jpeg == picture()
        assert observation.public_metadata()["pose_verified"] is False
        assert DEVICE not in str(observation.public_metadata())
        assert BOOT not in repr(observation) and "orange" not in repr(observation)
    thread.join(2)
    assert transport.closed and not errors
    assert [kind for kind, _, _ in seen] == [1, 2, 3]
    assert len({nonce for _, nonce, _ in seen}) == 3
    assert [payload for _, _, payload in seen] == [b"", bytes.fromhex(BOOT), bytes.fromhex(BOOT)]


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "22" * 16),
        ("image_id", "22" * 16),
        ("sha256", "00" * 32),
        ("width", 640),
        ("byte_count", 1),
        ("captured_ms", 2000),
        ("captured_ms", -1),
        ("pose_verified", True),
    ],
)
def test_snapshot_rejects_mismatched_or_stale_source(tmp_path, field, value):
    def mutate(kind, replies):
        if kind == 3:
            replies[0][1][field] = value
        return replies

    client, seen, transport, thread, errors = peer_client(tmp_path, mutate=mutate)
    with client:
        with pytest.raises(ObserverError):
            client.capture()
        with pytest.raises(ObserverError):
            client.status()  # broken stream cannot be reused
    thread.join(2)
    assert len(seen) == 2 and not errors and transport.closed


def test_wrong_paired_device_rejected_before_capture(tmp_path):
    def mutate(kind, replies):
        replies[0][1]["device_id"] = "00" * 6
        return replies

    client, seen, transport, thread, errors = peer_client(tmp_path, mutate=mutate)
    with pytest.raises(ObserverError):
        client.__enter__()
    thread.join(2)
    assert [kind for kind, _, _ in seen] == [1] and transport.closed and not errors


def test_finite_deadline_and_closed_transport_on_partial_packet(tmp_path):
    class Partial:
        closed = False

        def write(self, data):
            return len(data)

        def read(self, count):
            time.sleep(0.005)
            return b"SCOB" if not hasattr(self, "sent") else b""

        def close(self):
            self.closed = True

    link = Partial()
    link.sent = True
    profile = tmp_path / "pair.json"
    save_profile(profile, DEVICE)
    start = time.monotonic()
    with pytest.raises(ObserverError):
        ObserverClient(
            "port", profile, transport_factory=lambda port: link, timeout_s=1
        ).__enter__()
    assert link.closed and time.monotonic() - start < 2


@pytest.mark.parametrize("bad", ["nonce", "kind", "jpeg", "age", "status_boot"])
def test_mixed_transactions_and_invalid_jpeg_never_escape(tmp_path, bad):
    def mutate(kind, replies):
        if kind == 3:
            if bad == "nonce":
                replies[0][1]["image_id"] = "33" * 16
            if bad == "kind":
                replies[0] = (0x82, status())
            if bad == "jpeg":
                jpeg = b"not an image"
                replies[0][1]["byte_count"] = len(jpeg)
                replies[0][1]["sha256"] = hashlib.sha256(jpeg).hexdigest()
                replies[1] = (0x84, jpeg)
            if bad == "age":
                replies[0][1]["uptime_ms"] = 10000
            if bad == "status_boot":
                replies[0][1]["boot_id"] = "44" * 16
        return replies

    client, seen, transport, thread, errors = peer_client(tmp_path, mutate=mutate)
    with client:
        with pytest.raises(ObserverError):
            client.capture()
    thread.join(2)
    assert transport.closed and not errors


def test_serial_control_lines_inactive_before_open(monkeypatch):
    import serial

    from stackchan_autonomy.observer import open_serial

    events = []

    class Link:
        def __init__(self, **kw):
            assert kw["port"] is None

        def __setattr__(self, key, value):
            events.append((key, value))

        def open(self):
            events.append("open")

    monkeypatch.setattr(serial, "Serial", Link)
    open_serial("COM7")
    assert events.index(("dtr", False)) < events.index("open")
    assert events.index(("rts", False)) < events.index("open")


def test_cli_requires_pairing_consent_without_opening_port(capsys):
    from stackchan_autonomy.observer_cli import main

    assert main(["pair", "--port", "private-port"]) == 1
    assert capsys.readouterr().out == "PC_OBSERVER_PAIRING_REQUIRED\n"
    assert main(["status", "--port", "private-port", "--private-secret"]) == 2
    assert capsys.readouterr().out == "PC_OBSERVER_ARGUMENTS_INVALID\n"


@pytest.mark.parametrize(
    "model,value",
    [
        ("hello", {"read_only": 1}),
        ("hello", {"contract_version": True}),
        ("status", {"pose_verified": 0}),
    ],
)
def test_contract_assertions_reject_numeric_boolean_coercion(model, value):
    from stackchan_autonomy.observer_protocol import Hello, Status, parse_json

    record = hello() if model == "hello" else status()
    record.update(value)
    with pytest.raises(ObserverError):
        parse_json(Hello if model == "hello" else Status, json.dumps(record).encode())


def test_close_clears_partial_stream_and_hello(tmp_path):
    client, _, _, thread, errors = peer_client(tmp_path)
    with client:
        client.reader.feed(b"SCOB")
        client.close()
        assert client.hello is None and not client.reader.buffer and client.reader.noise == 0
    thread.join(2)
    assert not errors


def test_optimized_python_cannot_skip_build_recording_guard():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "import sys; sys.path.insert(0,'scripts'); from record_observer_build import require; require(False)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "OBSERVER_BUILD_INPUT_REJECTED" in result.stderr
