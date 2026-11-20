"""Offline SCFG feature-only tooling and privacy/safety contracts."""

import importlib.util
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scfg_offline", ROOT / "tools" / "scfg_offline.py")
assert SPEC is not None and SPEC.loader is not None
scfg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scfg)


def profile(count=1):
    body = b"SWK1" + bytes([count]) + b"\x00\x02" + bytes([3]) * (832 * count)
    return body + struct.pack("<I", zlib.crc32(body))


def test_profile_rejects_raw_audio_and_corruption():
    assert scfg.validate_profile(profile(3)) == 3
    for bad in (b"\0" * 2048, profile(3)[:-1], profile(1) + b"x", b"SWK1"):
        with pytest.raises(scfg.ProtocolError):
            scfg.validate_profile(bad)
    wrong = bytearray(profile())
    wrong[5] = 0
    wrong[6] = 0
    with pytest.raises(scfg.ProtocolError):
        scfg.validate_profile(wrong)


def test_chunk_transaction_includes_only_feature_profile():
    data = profile(3)
    encoded = scfg.make_bundle(data, 0x10203, 400)
    assert scfg.verify_bundle(encoded) == (0x10203, 7)
    assert len(encoded) < 4096
    with pytest.raises(scfg.ProtocolError):
        scfg.make_bundle(data, 1, 0)
    corrupt = bytearray(encoded)
    corrupt[-1] ^= 1
    with pytest.raises(scfg.ProtocolError):
        scfg.verify_bundle(corrupt)
    with pytest.raises(scfg.ProtocolError):
        scfg.verify_bundle(encoded[:-1])
    with pytest.raises(scfg.ProtocolError):
        scfg.verify_bundle(encoded + scfg.encode_frame(6, 2, 0, b""))


def test_cross_language_scfg_golden_packet():
    assert scfg.encode_frame(4, 0x01020304, 0, b"\x01\x00\x02\x00\x00\x00").hex() == (
        "5343464701040600040302010000010002000000c55fd066"
    )


def test_sack_has_fixed_error_only_response():
    header = struct.pack("<4sBBBBIH", b"SACK", 1, 5, 0, 1, 123, 7)
    ack = header + struct.pack("<I", zlib.crc32(header))
    assert scfg.decode_ack(ack) == (5, 0, 1, 123, 7)
    with pytest.raises(scfg.ProtocolError):
        scfg.decode_ack(ack + b"secret")


def test_cli_creates_private_local_only_bundle(tmp_path):
    source = tmp_path / "speaker.swk1"
    output = tmp_path / "enrollment.scfgbundle"
    source.write_bytes(profile())
    command = [sys.executable, str(ROOT / "tools" / "scfg_offline.py"), str(source)]
    inspected = subprocess.run(command, text=True, capture_output=True, check=True)
    assert "no device accessed" in inspected.stdout
    assert not output.exists()
    created = subprocess.run([*command, "--output", str(output)], text=True, capture_output=True)
    assert created.returncode == 0
    assert scfg.verify_bundle(output.read_bytes())[1] == 1
    if os.name != "nt":
        assert output.stat().st_mode & 0o077 == 0
    repeated = subprocess.run([*command, "--output", str(output)], capture_output=True)
    assert repeated.returncode != 0  # never silently overwrite private features
