"""Offline test of the ELF/slot gate; does not need ESP-IDF or a device."""

import csv
import importlib.util
import struct
from pathlib import Path

import pytest


@pytest.fixture
def validator():
    path = Path(__file__).resolve().parents[1] / "tools" / "check_idf_build.py"
    spec = importlib.util.spec_from_file_location("check_idf_build", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_xtensa_elf_and_app_size(tmp_path, validator):
    elf, app = tmp_path / "app.elf", tmp_path / "app.bin"
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 1
    header[5] = 1
    header[6] = 1
    struct.pack_into("<H", header, 18, 94)
    elf.write_bytes(header)
    app.write_bytes(b"example-app")
    result = validator.validate(elf, app, validator.EXPECTED_IDF_SHA)
    assert result["installed"] is False
    assert result["elf_machine"] == 94
    assert result["app"]["size"] == 11
    with pytest.raises(ValueError, match="pinned"):
        validator.validate(elf, app, "wrong")
    header[18] = 3
    elf.write_bytes(header)
    with pytest.raises(ValueError, match="Xtensa"):
        validator.validate(elf, app, validator.EXPECTED_IDF_SHA)
    header[18] = 94
    elf.write_bytes(header)
    app.write_bytes(b"x" * (validator.OBSERVED_K151_OTA_SLOT + 1))
    with pytest.raises(ValueError, match="slot"):
        validator.validate(elf, app, validator.EXPECTED_IDF_SHA)


def test_hold_build_checks_observed_app_slots(validator):
    hold = Path(__file__).resolve().parents[1] / "esp_app"
    defaults = dict(
        line.split("=", 1)
        for line in (hold / "sdkconfig.defaults").read_text().splitlines()
        if line.startswith("CONFIG_PARTITION_TABLE_")
    )
    assert defaults.get("CONFIG_PARTITION_TABLE_CUSTOM") == "y"
    table = hold / defaults["CONFIG_PARTITION_TABLE_CUSTOM_FILENAME"].strip('"')
    rows = csv.reader(
        line for line in table.read_text().splitlines() if line.strip() and not line.startswith("#")
    )
    apps = {
        (label, subtype, int(offset, 0), int(size, 0))
        for label, kind, subtype, offset, size, _flags in rows
        if kind == "app"
    }
    size = validator.OBSERVED_K151_OTA_SLOT
    assert apps == {("ota_0", "ota_0", 0x20000, size), ("ota_1", "ota_1", 0x510000, size)}


def test_realtime_route_and_bearer_log_check(validator):
    route = b"/v1/realtime?model=gpt-realtime-2.1-mini"
    validator.verify_realtime_transport(b"app\0" + route + b"\0")
    with pytest.raises(ValueError, match="missing"):
        validator.verify_realtime_transport(b"app\0")
    for message in (b"Error write Upgrade header", b"Write upgrade request"):
        with pytest.raises(ValueError, match="credential"):
            validator.verify_realtime_transport(route + b"\0" + message)


@pytest.mark.parametrize("corruption", ["truncated", "elf64", "big_endian", "invalid_version"])
def test_rejects_invalid_elf_identity(tmp_path, validator, corruption):
    elf, app = tmp_path / "app.elf", tmp_path / "app.bin"
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4:7] = bytes((1, 1, 1))
    struct.pack_into("<H", header, 18, 94)
    if corruption == "truncated":
        header = header[:20]
    elif corruption == "elf64":
        header[4] = 2
    elif corruption == "big_endian":
        header[5] = 2
    else:
        header[6] = 0
    elf.write_bytes(header)
    app.write_bytes(b"app")
    with pytest.raises(ValueError, match="ELF"):
        validator.validate(elf, app, validator.EXPECTED_IDF_SHA)
