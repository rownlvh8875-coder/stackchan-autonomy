"""Independently constructed ESP image fixtures, no device or firmware install."""

import hashlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_resource_bench as bench

ELF_SHA = hashlib.sha256(b"fixture-elf").hexdigest()


def image(payload, address=0x3C020020, chip=9, project=b"k151_resource_bench", minimum=0):
    header = bytearray(24)
    header[0:2] = bytes([0xE9, 1])
    struct.pack_into("<H", header, 12, chip)
    struct.pack_into("<H", header, 15, minimum)
    header[23] = 1
    struct.pack_into("<H", header, 17, 0xFFFF)
    desc = bytearray(256)
    struct.pack_into("<I", desc, 0, 0xABCD5432)
    desc[16:28] = b"012345abcdef"
    project = project + b"\0"
    desc[48 : 48 + len(project)] = project
    desc[144:176] = bytes.fromhex(ELF_SHA)
    data = bytes(desc) + payload
    app = bytes(header) + struct.pack("<II", address, len(data)) + data
    checksum = 0xEF
    for byte in data:
        checksum ^= byte
    app += bytes((15 - len(app) % 16) % 16) + bytes([checksum])
    return app + hashlib.sha256(app).digest()


@pytest.fixture
def pack(monkeypatch):
    payload = b"test-pinned-model"
    monkeypatch.setattr(bench, "PACK_PREFIX", payload)
    monkeypatch.setattr(bench, "PACK_BYTES", len(payload))
    monkeypatch.setattr(bench, "PACK_SHA256", hashlib.sha256(payload).hexdigest())
    return payload


def test_exact_image_and_sector_scope(pack):
    app = image(pack)
    result = bench.inspect_image(app, ELF_SHA)
    assert result["app_version"] == "012345abcdef"
    assert result["write_offset"] == 0x510000
    assert result["write_bytes"] == len(app)
    assert result["erase_span_bytes"] == (len(app) + 4095) // 4096 * 4096
    assert result["install_authorized"] is False
    assert result["operating_admission"] is False
    assert result["partition_table_changed"] is False


@pytest.mark.parametrize(
    "kind", ["chip", "ram", "corrupt", "truncated", "duplicate", "missing", "oversized"]
)
def test_reject_invalid_image(pack, kind):
    app = image(pack)
    if kind == "chip":
        app = image(pack, chip=0)
    if kind == "ram":
        app = image(pack, address=0x3FC90000)
    if kind == "corrupt":
        app = app[:-1] + bytes([app[-1] ^ 1])
    if kind == "truncated":
        app = app[:60]
    if kind == "duplicate":
        app = image(pack + pack)
    if kind == "missing":
        app = image(b"other")
    if kind == "oversized":
        app = image(pack + bytes(5_177_344))
    with pytest.raises(ValueError):
        bench.inspect_image(app, ELF_SHA)


def test_elf_must_match_image_descriptor(pack):
    app = image(pack)
    # Valid image hash/checksum cannot bind an unrelated ELF to this bin.
    with pytest.raises(ValueError):
        bench.inspect_image(app, elf_sha256="ff" * 32)


@pytest.mark.parametrize(
    "source", ["", "HEAD", "f63fb84", "f" * 39, "g" * 40, "f" * 41, "f" * 40 + "\n"]
)
def test_build_commit_required(source):
    with pytest.raises(ValueError):
        bench.validate_source_head(source)


def test_image_version_must_bind_source_commit():
    source = "abcdef0123456789" * 2 + "abcdef01"
    with pytest.raises(ValueError):
        bench.bind_source_head("1", source)
    assert bench.bind_source_head(source[:12], source) == source
