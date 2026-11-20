"""Synthetic OTA records; never read an operator's flash in tests."""

import binascii
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def record(seq, state=2):
    # Same seed as pinned IDF otatool; seq_label is intentionally private.
    return struct.pack(
        "<I20sII",
        seq,
        b"private-label-token!",
        state,
        binascii.crc32(struct.pack("<I", seq), 0xFFFFFFFF),
    )


def region(first, second):
    return first + b"\xff" * (4096 - 32) + second + b"\xff" * (4096 - 32)


@pytest.mark.parametrize("seq,slot", [(1, "ota_0"), (2, "ota_1"), (7, "ota_0"), (0, "ota_1")])
def test_crc_and_unsigned_slot_mapping(seq, slot):
    from offline_factory_recovery import inspect_otadata

    report = inspect_otadata(region(record(seq), b"\xff" * 32))
    assert report["without_rollback_candidate"] == slot
    assert report["with_rollback_candidate"] == slot
    assert report["running_slot_verified"] is False
    assert report["spare_slot_verified"] is False
    assert "private-label" not in json.dumps(report)


@pytest.mark.parametrize("state", [3, 4, 123456])
def test_invalid_aborted_or_unknown_state_not_selected(state):
    from offline_factory_recovery import inspect_otadata

    report = inspect_otadata(region(record(9, state), record(2)))
    assert report["without_rollback_candidate"] == "ota_1"


def test_pending_verify_depends_on_factory_bootloader_policy():
    from offline_factory_recovery import inspect_otadata

    report = inspect_otadata(region(record(7, 1), record(2)))
    assert report["without_rollback_candidate"] == "ota_0"
    assert report["with_rollback_candidate"] == "ota_1"
    assert report["factory_bootloader_policy_verified"] is False


def test_new_undefined_tie_crc_corruption_and_erased_records():
    from offline_factory_recovery import inspect_otadata

    for state in (0, 0xFFFFFFFF):
        report = inspect_otadata(region(record(3, state), record(3)))
        assert report["selected_record_without_rollback"] == 0
    bad = bytearray(record(4))
    bad[28] ^= 1
    report = inspect_otadata(region(bytes(bad), b"\xff" * 32))
    assert report["records"][0]["crc_valid"] is False
    assert report["without_rollback_candidate"] is None
    assert report["with_rollback_candidate"] is None
    with pytest.raises(ValueError):
        inspect_otadata(b"\xff" * 4096)
