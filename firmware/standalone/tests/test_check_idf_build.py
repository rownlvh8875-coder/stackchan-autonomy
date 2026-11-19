"""Offline test of the ELF/slot gate; does not need ESP-IDF or a device."""

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
