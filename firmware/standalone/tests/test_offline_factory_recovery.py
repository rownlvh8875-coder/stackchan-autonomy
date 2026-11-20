"""Use generated synthetic 16MiB images, never device/customer flash data."""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from offline_factory_recovery import EXPECTED_PARTITIONS, verify_copies  # noqa: E402

ENTRY = struct.Struct("<2sBBII16sI")
IMAGE_BYTES = 0x1000000
TABLE_START = 0x8000
MD5_PREFIX = b"\xeb\xeb" + b"\xff" * 14


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    temp = tmp_path_factory.mktemp("safe_factory_fixture")
    data = bytearray(b"\xff" * IMAGE_BYTES)
    for i, (label, address, length, part_type, subtype) in enumerate(EXPECTED_PARTITIONS):
        raw_label = label.encode().ljust(16, b"\0")
        record = ENTRY.pack(
            b"\xaa\x50",
            part_type,
            subtype,
            int(address, 16),
            length,
            raw_label,
            0,
        )
        data[TABLE_START + i * ENTRY.size : TABLE_START + (i + 1) * ENTRY.size] = record
    md5_at = TABLE_START + len(EXPECTED_PARTITIONS) * ENTRY.size
    digest = hashlib.md5(data[TABLE_START:md5_at], usedforsecurity=False).digest()
    data[md5_at : md5_at + 32] = MD5_PREFIX + digest
    original = bytes(data)
    first = temp / "fixture-a.bin"
    second = temp / "fixture-b.bin"
    first.write_bytes(original)
    second.write_bytes(original)
    return first, second, hashlib.sha256(original).hexdigest()


def test_two_full_copies_and_layout_not_install_authorization(synthetic):
    a, b, digest = synthetic
    report = verify_copies(a, b, digest)
    assert report["partition_count"] == 7
    assert report["ota_partition_count"] == 2
    assert report["sha256_verified_locally"] == digest
    assert report["install_authorized"] is False
    assert report["active_slot_identified"] is False
    assert report["restore_write_tested"] is False
    assert report["flash_modified"] is False


def test_refuse_identical_input_path(synthetic):
    a, _b, digest = synthetic
    with pytest.raises(Exception):
        verify_copies(a, a, digest)


def test_refuse_modified_or_missing_backup(synthetic, tmp_path):
    a, b, digest = synthetic
    changed = tmp_path / "changed.bin"
    with b.open("rb") as original, changed.open("wb") as output:
        data = bytearray(original.read())
        data[0x12345] ^= 1
        output.write(data)
    with pytest.raises(Exception):
        verify_copies(a, changed, digest)
    with pytest.raises(Exception):
        verify_copies(a, tmp_path / "no-file.bin", digest)
    with pytest.raises(Exception):
        verify_copies(a, b, "0" * 64)


def test_read_only_cli_and_no_private_paths_in_result(synthetic):
    a, b, digest = synthetic
    tool = TOOLS / "offline_factory_recovery.py"
    done = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--factory-a",
            str(a),
            "--factory-b",
            str(b),
            "--expected-sha256",
            digest,
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    result = json.loads(done.stdout)
    assert result["install_authorized"] is False
    assert str(a) not in done.stdout
    assert str(b) not in done.stdout
    assert "COM" not in done.stdout
    assert done.stderr == ""
