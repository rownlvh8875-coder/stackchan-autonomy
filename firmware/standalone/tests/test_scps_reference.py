"""SCPS reference uses only synthetic credentials, no USB or external network."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from scps_reference import OfflineDeviceEmulator, PcSession  # noqa: E402

FAKE_PASS = "not-a-real-password"
FAKE_KEY = "example-not-real-api-token-012345"


def _make_pair():
    device = OfflineDeviceEmulator()
    pc = PcSession(device.device_hello)
    display_code = device.accept_pc_hello(pc.pc_hello, True)
    assert display_code == pc.sas and len(display_code) == 8 and display_code.isdecimal()
    return device, pc, display_code


def test_success_pairing_and_one_shot_seal():
    device, pc, code = _make_pair()
    sealed = pc.seal(b"HomeNetwork", FAKE_PASS, FAKE_KEY, code, True)
    assert FAKE_KEY.encode() not in sealed and FAKE_PASS.encode() not in sealed
    data = device.open_sealed(sealed, True, True)
    assert (data.ssid, data.password, data.api_key) == (b"HomeNetwork", FAKE_PASS, FAKE_KEY)
    with pytest.raises(ValueError):
        device.open_sealed(sealed, True, True)
    with pytest.raises(ValueError):
        pc.seal(b"HomeNetwork", FAKE_PASS, FAKE_KEY, code, True)


def test_wrong_sas_and_no_trusted_display_refuse():
    device, pc, code = _make_pair()
    with pytest.raises(ValueError):
        pc.seal(b"HomeNetwork", FAKE_PASS, FAKE_KEY, "0000000x", True)
    with pytest.raises(ValueError):
        pc.seal(b"HomeNetwork", FAKE_PASS, FAKE_KEY, code, False)
    packet = pc.seal(b"HomeNetwork", FAKE_PASS, FAKE_KEY, code, True)
    with pytest.raises(ValueError):
        device.open_sealed(packet, False, True)


def test_ciphertext_tamper_fails_and_consumes_session():
    device, pc, code = _make_pair()
    blob = bytearray(pc.seal(b"Net", FAKE_PASS, FAKE_KEY, code, True))
    blob[-3] ^= 0x01
    with pytest.raises(ValueError, match="authentication failed"):
        device.open_sealed(bytes(blob), True, True)
    with pytest.raises(ValueError):
        device.open_sealed(bytes(blob), True, True)


def test_header_length_tamper_fails():
    device, pc, code = _make_pair()
    blob = bytearray(pc.seal(b"Net", FAKE_PASS, FAKE_KEY, code, True))
    blob[17] ^= 0x01
    with pytest.raises(ValueError):
        device.open_sealed(bytes(blob), True, True)


def test_sealed_message_bound_to_one_device_session():
    dev1, pc, code = _make_pair()
    blob = pc.seal(b"Net", FAKE_PASS, FAKE_KEY, code, True)
    other = OfflineDeviceEmulator()
    other.accept_pc_hello(pc.pc_hello, True)
    with pytest.raises(ValueError):
        other.open_sealed(blob, True, True)
    assert dev1.open_sealed(blob, True, True).api_key == FAKE_KEY


def test_handshake_requires_physical_window_and_point_valid():
    dev = OfflineDeviceEmulator()
    pc = PcSession(dev.device_hello)
    with pytest.raises(ValueError):
        dev.accept_pc_hello(pc.pc_hello, False)
    fake = bytearray(pc.pc_hello)
    fake[5] = 0
    with pytest.raises(ValueError):
        dev.accept_pc_hello(bytes(fake), True)
    with pytest.raises(ValueError):
        PcSession(dev.device_hello[:-1])
    assert dev.accept_pc_hello(pc.pc_hello, True) == pc.sas
    with pytest.raises(ValueError):
        dev.accept_pc_hello(pc.pc_hello, True)


def test_stop_never_accepts_sealed_data():
    device, pc, code = _make_pair()
    blob = pc.seal(b"Net", FAKE_PASS, FAKE_KEY, code, True)
    with pytest.raises(ValueError):
        device.open_sealed(blob, True, True, physical_stop=True)
    with pytest.raises(ValueError):
        device.open_sealed(blob, True, True)


@pytest.mark.parametrize(
    "ssid,pw,token",
    [
        (b"", FAKE_PASS, FAKE_KEY),
        (b"Bad\x00Net", FAKE_PASS, FAKE_KEY),
        (b"Network", "short", FAKE_KEY),
        (b"Network", FAKE_PASS, "too-short"),
        (b"Network", "g" * 64, FAKE_KEY),
        (b"Network", FAKE_PASS, "A" * 221),
    ],
)
def test_invalid_credential_data_rejected(ssid, pw, token):
    device, pc, code = _make_pair()
    with pytest.raises(ValueError):
        pc.seal(ssid, pw, token, code, True)
