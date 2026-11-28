"""SCPS framed serial transport integration against an in-memory device only."""

from __future__ import annotations

import getpass
import io
import json
import sys
import zlib
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import scps_usb_cli as cli  # noqa: E402
import scps_usb_wire as wire  # noqa: E402
from scps_reference import OfflineDeviceEmulator  # noqa: E402
from scps_usb_cli import run_pairing  # noqa: E402
from scps_usb_wire import Frame, Op, ScpsWireError, decode, encode, read_one, write_one  # noqa: E402


class FakePort:
    """Emulates serial byte fragments and two local physical decisions."""

    def __init__(self, *, wrong_ack: bool = False, touch_completed: bool = True):
        self.device = OfflineDeviceEmulator()
        self.rx = bytearray(encode(Frame(Op.DEVICE_HELLO, self.device.device_hello)))
        self.sas = None
        self.writes = []
        self.credentials = None
        self.wrong_ack = wrong_ack
        self.touch_completed = touch_completed

    def read(self, size: int) -> bytes:
        take = min(size, 7, len(self.rx))
        result = bytes(self.rx[:take])
        del self.rx[:take]
        return result

    def write(self, wire: bytes) -> int:
        frame = decode(wire)
        self.writes.append(frame)
        if frame.op is Op.PC_HELLO:
            self.sas = self.device.accept_pc_hello(frame.payload, owner_window=True)
            reply = Op.DENIED if self.wrong_ack else Op.DISPLAY_READY
            self.rx.extend(encode(Frame(reply)))
        elif frame.op is Op.SEALED:
            assert self.sas is not None
            self.credentials = self.device.open_sealed(
                frame.payload, local_sas_approved=True, owner_window=True
            )
            self.rx.extend(encode(Frame(Op.PENDING_TOUCH)))
            if self.touch_completed:
                self.rx.extend(encode(Frame(Op.COMPLETED)))
        elif frame.op is Op.STOP:
            self.device.stop()
        else:
            raise AssertionError("unexpected op")
        return len(wire)


def test_wire_all_opcode_shapes_and_crc():
    for op in Op:
        if op in (Op.DEVICE_HELLO, Op.PC_HELLO):
            payload = bytes(range(86))
        elif op is Op.SEALED:
            payload = bytes(range(100))
        elif op is Op.LOCAL_SETUP_FAULT:
            payload = b"\x04"
        else:
            payload = b""
        assert decode(encode(Frame(op, payload))) == Frame(op, payload)
    with pytest.raises(ScpsWireError):
        decode(b"SCFG\x01\x01\x00\x00\x00\x00\x00\x00")
    corrupted = bytearray(encode(Frame(Op.PC_HELLO, bytes(86))))
    corrupted[-1] ^= 0x01
    with pytest.raises(ScpsWireError):
        decode(bytes(corrupted))
    with pytest.raises(ScpsWireError):
        encode(Frame(Op.SEALED, bytes(360)))


def test_local_fault_report_cannot_advance_setup():
    port = FakePort()
    port.rx[:] = encode(Frame(Op.LOCAL_SETUP_FAULT, b"\x07"))
    with pytest.raises(wire.ScpsInvalidFrame):
        wire.expect(port, Op.PENDING_TOUCH, 20)
    assert not port.writes


@pytest.mark.parametrize("prefix", [b"", b"synthetic startup output\r\n\x00SS", b"x" * 1433])
def test_full_encrypted_pairing_and_no_secret_echo(prefix):
    port = FakePort()
    port.rx[:0] = prefix
    messages = []
    password = "fake-password-12345"
    api = "synthetic-not-real-api-key-012345"
    entries = iter(
        [
            "HomeNetwork",
        ]
    )

    def visible(prompt: str) -> str:
        if "8 digits" in prompt:
            assert port.sas is not None
            return port.sas
        return next(entries)

    secrets = iter([password, api])
    assert run_pairing(
        port, text_input=visible, hidden_input=lambda _: next(secrets), say=messages.append
    )
    assert port.credentials is not None
    assert port.credentials.password == password
    assert port.credentials.api_key == api
    assert [x.op for x in port.writes] == [Op.PC_HELLO, Op.SEALED]
    assert password not in repr(port.writes)
    assert api not in repr(port.writes)
    assert not any(password in m or api in m for m in messages)
    screen = next(
        index for index, message in enumerate(messages) if "hold the K151 screen" in message
    )
    head = next(
        index for index, message in enumerate(messages) if "touch the top of the head" in message
    )
    assert screen < head


@pytest.mark.parametrize("prefix_length", [2048, 2049])
def test_first_frame_prefix_discard_has_a_byte_limit(prefix_length):
    port = FakePort()
    port.rx[:0] = b"x" * prefix_length

    if prefix_length == 2048:
        assert wire.expect(port, Op.DEVICE_HELLO, 20).op is Op.DEVICE_HELLO
    else:
        with pytest.raises(wire.ScpsInvalidFrame):
            wire.expect(port, Op.DEVICE_HELLO, 20)


def test_corrupt_first_frame_is_rejected_even_with_a_valid_frame_behind_it():
    port = FakePort()
    valid = bytes(port.rx)
    invalid = bytearray(valid)
    invalid[-1] ^= 1
    port.rx[:] = b"synthetic startup output\r\n" + invalid + valid

    with pytest.raises(wire.ScpsInvalidFrame):
        wire.expect(port, Op.DEVICE_HELLO, 20)
    assert port.rx == valid


def test_bytes_before_display_ready_remain_a_protocol_error():
    port = FakePort()
    port.rx[:] = b"unexpected" + encode(Frame(Op.DISPLAY_READY))
    with pytest.raises(wire.ScpsInvalidFrame):
        wire.expect(port, Op.DISPLAY_READY, 20)


def test_first_frame_header_shares_the_startup_prefix_deadline(monkeypatch):
    port = FakePort()
    port.rx[:0] = b"x" * 15
    clock = count()
    monkeypatch.setattr(wire, "time", SimpleNamespace(monotonic=clock.__next__))

    with pytest.raises(wire.ScpsResponseTimeout):
        wire.expect(port, Op.DEVICE_HELLO, 20)
    assert not port.writes


@pytest.mark.parametrize("matches", [True, False])
def test_saved_sources_run_only_after_matching_local_code(matches):
    port = FakePort()
    messages = []
    reads = []
    wifi = (b"synthetic-network", "synthetic-passphrase")
    key = "synthetic-openai-key"

    def local_code(prompt):
        assert "8 digits" in prompt
        assert not reads
        assert port.sas is not None
        return port.sas if matches else "invalid"

    def read_wifi():
        reads.append("wifi")
        return wifi

    def read_key():
        reads.append("api")
        return key

    def manual_secret(_):
        pytest.fail("saved entries should not ask for manual input")

    def pair():
        return run_pairing(
            port,
            text_input=local_code,
            hidden_input=manual_secret,
            say=messages.append,
            load_wifi=read_wifi,
            load_api_key=read_key,
        )

    if not matches:
        with pytest.raises(ScpsWireError, match="pairing codes do not match"):
            pair()
        assert reads == []
        assert [frame.op for frame in port.writes] == [Op.PC_HELLO, Op.STOP]
        return

    assert pair()
    assert reads == ["wifi", "api"]
    assert (port.credentials.ssid, port.credentials.password, port.credentials.api_key) == (
        *wifi,
        key,
    )
    assert [frame.op for frame in port.writes] == [Op.PC_HELLO, Op.SEALED]
    assert all(secret not in "\n".join(messages) for secret in (wifi[0].decode(), wifi[1], key))


def test_unavailable_saved_wifi_uses_manual_wifi_and_keeps_saved_key():
    port = FakePort()
    key = "synthetic-openai-key"

    def visible(prompt):
        return port.sas if "8 digits" in prompt else "synthetic-network"

    def hidden(prompt):
        assert "Wi-Fi password" in prompt
        return "synthetic-password"

    assert run_pairing(
        port,
        text_input=visible,
        hidden_input=hidden,
        say=lambda _: None,
        load_wifi=lambda: None,
        load_api_key=lambda: key,
    )
    assert port.credentials.ssid == b"synthetic-network"
    assert port.credentials.api_key == key


@pytest.mark.parametrize("unavailable_at", ["Wi-Fi password", "OpenAI API key"])
def test_unavailable_hidden_input_aborts_before_echoing_or_sending_secrets(
    monkeypatch, unavailable_at
):
    port = FakePort()
    terminal = io.StringIO()
    fallback_reads = []

    def read_with_echo(prompt, *_args, **_kwargs):
        fallback_reads.append(prompt)
        terminal.write("synthetic-echoed-secret")
        return "synthetic-echoed-secret"

    def hidden_input(prompt):
        if prompt.startswith(unavailable_at):
            return getpass.fallback_getpass(prompt, stream=terminal)
        return "synthetic-hidden-value"

    monkeypatch.setattr(getpass, "_raw_input", read_with_echo)
    with pytest.raises(ScpsWireError, match="secure console input unavailable"):
        run_pairing(
            port,
            text_input=lambda prompt: port.sas if "8 digits" in prompt else "SyntheticNetwork",
            hidden_input=hidden_input,
            say=lambda _: None,
        )
    assert fallback_reads == [] and terminal.getvalue() == ""
    assert port.credentials is None
    assert [frame.op for frame in port.writes] == [Op.PC_HELLO, Op.STOP]


def test_wrong_sas_never_sends_credentials():
    port = FakePort()
    with pytest.raises(ScpsWireError):
        run_pairing(
            port,
            text_input=lambda _: "0000000x",
            hidden_input=lambda _: pytest.fail("secret prompt before SAS"),
            say=lambda _: None,
        )
    assert all(x.op is not Op.SEALED for x in port.writes)
    assert port.writes[-1].op is Op.STOP


def test_unexpected_status_never_prompts_secret():
    port = FakePort(wrong_ack=True)
    with pytest.raises(ScpsWireError):
        run_pairing(
            port,
            text_input=lambda _: pytest.fail("no input permitted"),
            hidden_input=lambda _: pytest.fail("secret request"),
            say=lambda _: None,
        )
    assert port.writes[-1].op is Op.STOP


def test_partial_write_fails_closed_no_retry():
    class ShortPort:
        def write(self, wire: bytes) -> int:
            # Driver accepts a partial byte sequence. Do not interpret any
            # sent bytes as a valid PC public key or fake device state.
            return len(wire) - 1

    port = ShortPort()
    with pytest.raises(ScpsWireError, match="incomplete"):
        write_one(port, Frame(Op.PC_HELLO, bytes(86)))


def test_reads_fragmented_frame():
    port = FakePort()
    assert read_one(port).op is Op.DEVICE_HELLO


@pytest.mark.parametrize("open_fails", [False, True])
def test_cli_cues_head_touch_only_after_opening_without_reset(monkeypatch, open_fails):
    wire = FakePort()
    hello = bytes(wire.rx)
    wire.rx.clear()
    events = []

    class Serial:
        def __init__(self, port, **settings):
            self.port = port
            self.dtr = self.rts = True
            self.is_open = False
            if self.port is not None:
                self.open()

        def open(self):
            if open_fails:
                raise OSError
            self.is_open = True
            events.append(("open", self.port, self.dtr, self.rts))

        def __enter__(self):
            if not self.is_open:
                self.open()
            return self

        def __exit__(self, *exc):
            self.is_open = False

    def visible(message, *, flush=False):
        if "머리 윗면" in message:
            assert flush
            if events and events[-1][0] == "open":
                events.append(("touch",))
                wire.rx.extend(hello)  # The device sends its hello only once.

    def receive(port, **_kwargs):
        assert port.is_open
        assert wire.rx, "the PC missed the device's only initial hello"
        assert read_one(wire).op is Op.DEVICE_HELLO
        return True

    monkeypatch.setitem(
        sys.modules, "serial", SimpleNamespace(Serial=Serial, SerialException=OSError)
    )
    monkeypatch.setattr(cli, "print", visible, raising=False)
    monkeypatch.setattr(cli, "run_pairing", receive)
    assert cli.main(["--port", "COM3", "--interactive"]) == int(open_fails)
    assert events == ([] if open_fails else [("open", "COM3", False, False), ("touch",)])


@pytest.mark.parametrize(
    ("hello_failure", "stage", "reason", "sent"),
    [
        ("timeout", "device_hello", "response_timeout", [Op.STOP]),
        ("io_error", "device_hello", "serial_io", [Op.STOP]),
        ("prefix_limit", "device_hello", "startup_prefix_limit", [Op.STOP]),
        ("partial_prefix", "device_hello", "startup_without_frame", [Op.STOP]),
        ("bad_version", "device_hello", "invalid_header", [Op.STOP]),
        ("bad_length", "device_hello", "invalid_length", [Op.STOP]),
        ("bad_crc", "device_hello", "invalid_body", [Op.STOP]),
        ("sensor_read", "device_hello", "device_sensor_read", [Op.STOP]),
        ("usb_start", "device_hello", "device_usb_start", [Op.STOP]),
        ("bad_fault_code", "device_hello", "invalid_body", [Op.STOP]),
        (None, "display_ready", "device_denied", [Op.PC_HELLO, Op.STOP]),
    ],
)
def test_cli_distinguishes_early_pairing_failures_without_exposing_details(
    monkeypatch, capsys, tmp_path, hello_failure, stage, reason, sent
):
    class Serial(FakePort):
        def __init__(self, **_settings):
            super().__init__(wrong_ack=True)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def read(self, size):
            if hello_failure == "timeout":
                return b""
            if hello_failure == "io_error":
                raise OSError("internal test detail")
            return super().read(size)

    port = Serial()
    if hello_failure == "prefix_limit":
        port.rx[:0] = b"x" * 2049
    elif hello_failure == "partial_prefix":
        port.rx[:] = b"synthetic-rx-only\x01SCP"
    elif hello_failure == "bad_version":
        port.rx[4] ^= 1
    elif hello_failure == "bad_length":
        port.rx[6] += 1
    elif hello_failure == "bad_crc":
        port.rx[-1] ^= 1
    elif hello_failure in ("sensor_read", "usb_start", "bad_fault_code"):
        reason_byte = {"sensor_read": 4, "usb_start": 6, "bad_fault_code": 255}[hello_failure]
        packet = b"SCPW\x01\x09\x01\x00" + bytes([reason_byte])
        port.rx = bytearray(packet + zlib.crc32(packet).to_bytes(4, "little"))
    monkeypatch.setitem(
        sys.modules, "serial", SimpleNamespace(Serial=lambda **_: port, SerialException=OSError)
    )
    clock = count()
    monkeypatch.setattr(wire, "time", SimpleNamespace(monotonic=lambda: next(clock) / 1000))

    receipt = tmp_path / "setup-failure.json"
    assert cli.main(["--port", "COM3", "--interactive", "--failure-receipt", str(receipt)]) == 1
    output = capsys.readouterr().out
    assert f"Pairing failed at {stage} ({reason})." in output
    assert "internal test detail" not in output
    assert "synthetic-rx-only" not in output
    assert "PC pairing code" not in output
    assert json.loads(receipt.read_text(encoding="utf-8")) == {"stage": stage, "reason": reason}
    assert [frame.op for frame in port.writes] == sent
