"""SCPS framed serial transport integration against an in-memory device only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

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


def test_full_encrypted_pairing_and_no_secret_echo():
    port = FakePort()
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
    class ShortPort(FakePort):
        def write(self, wire: bytes) -> int:
            super().write(wire)
            return len(wire) - 1

    port = ShortPort()
    with pytest.raises(ScpsWireError, match="incomplete"):
        write_one(port, Frame(Op.PC_HELLO, bytes(86)))


def test_reads_fragmented_frame():
    port = FakePort()
    assert read_one(port).op is Op.DEVICE_HELLO
