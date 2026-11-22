"""Rehearse the reviewed ROM adapter with ESP32-S3 and esptool doubles."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import paid_trial_rom as rom  # noqa: E402
from paid_trial_sequence import TrialStep  # noqa: E402
from test_paid_trial_binding import review as review_fixture  # noqa: E402

review = review_fixture


class Chip:
    IS_STUB = False
    secure_download_mode = False

    def __init__(self, owner, index):
        self.owner = owner
        self.index = index
        self._port = self

    def get_chip_revision(self):
        return 2

    def read_mac(self):
        if self.owner.wrong_recovery_board and self.index == 2:
            return (4, 0, 0, 0, 0, 1)
        return (2, 0, 0, 0, 0, 1)

    def get_secure_boot_enabled(self):
        return False

    def get_flash_encryption_enabled(self):
        return False

    def close(self):
        self.owner.events.append(("close", self.index))


class Tool:
    def __init__(self, paths):
        self.events = []
        self.connections = 0
        self.wrong_recovery_board = False
        self.bad_metadata = False
        self.bad_final_metadata = False
        self.fail_ota_restore = False
        self.flash = {0x510000: paths.ota1.read_bytes(), 0x9000: paths.nvs.read_bytes()}

    def detect(self, port, **kwargs):
        assert port == "mock-port" and kwargs["connect_attempts"] == 1
        self.connections += 1
        self.events.append(("connect", self.connections))
        return Chip(self, self.connections)

    def attach_flash(self, chip):
        assert type(chip) is Chip

    def detect_flash_size(self, chip):
        return "16MB"

    def read_flash(self, chip, address, size, **kwargs):
        assert kwargs["no_progress"] and "output" not in kwargs
        self.events.append(("read", chip.index, address))
        changed = self.bad_final_metadata and ("write", 2, 0x9000) in self.events
        return (b"q" if self.bad_metadata or changed else b"m") * size

    def verify_flash(self, chip, regions, **kwargs):
        address, data = regions[0]
        assert len(regions) == 1 and kwargs.get("diff") is False
        self.events.append(("verify", chip.index, address))
        if self.flash[address] != data or (
            chip.index == 2 and self.fail_ota_restore and address == 0x510000
        ):
            raise ValueError("synthetic private verification error")

    def write_flash(self, chip, regions, **kwargs):
        address, data = regions[0]
        assert len(regions) == 1 and kwargs.get("erase_all") is False
        assert all(kwargs[key] == "keep" for key in ("flash_mode", "flash_freq", "flash_size"))
        self.flash[address] = data
        self.events.append(("write", chip.index, address))

    def reset_chip(self, chip, mode):
        assert mode == "hard-reset"
        self.events.append(("reset", chip.index))


def run(review, monkeypatch, command_setup=lambda _tool: None):
    paths, _, _ = review
    tool = Tool(paths)
    command_setup(tool)
    monkeypatch.setattr(rom, "_load_esptool", lambda: (tool.detect, Chip, tool))

    def exercise():
        assert tool.events[-1] == ("close", 1)
        tool.events.append(("trial", 1))
        tool.flash[0x9000] = b"trial changed the NVS"
        return False

    result = rom.run_rom_paid_trial(paths, "mock-port", lambda port: port == "mock-port", exercise)
    return result, tool, paths


def test_verified_ranges_survive_failed_turn_with_usb_closed_during_turn(review, monkeypatch):
    result, tool, paths = run(review, monkeypatch)
    assert result.trial_failure is TrialStep.BOOT_AND_RUN_ONE_TURN
    assert result.factory_boot_requested
    assert [event for event in tool.events if event[0] == "write"] == [
        ("write", 1, 0x510000),
        ("write", 2, 0x510000),
        ("write", 2, 0x9000),
    ]
    assert tool.events.index(("verify", 2, 0x510000)) < tool.events.index(("write", 2, 0x9000))
    assert tool.flash[0x9000] == paths.nvs.read_bytes()
    assert tool.events[-2:] == [("reset", 2), ("close", 2)]


@pytest.mark.parametrize(
    ("attribute", "failure", "no_write_after"),
    [
        ("bad_metadata", TrialStep.PREFLIGHT, 0),
        ("wrong_recovery_board", TrialStep.REBIND_FOR_RESTORE, 1),
        ("fail_ota_restore", TrialStep.VERIFY_ORIGINAL_OTA1, 2),
        ("bad_final_metadata", TrialStep.VERIFY_FACTORY_METADATA, 3),
    ],
)
def test_failed_gate_never_writes_unverified_range_or_reboots_factory(
    review, monkeypatch, capsys, attribute, failure, no_write_after
):
    result, tool, _ = run(review, monkeypatch, lambda tool: setattr(tool, attribute, True))
    assert failure in (result.trial_failure, result.recovery_failure)
    assert not result.factory_boot_requested
    assert len([event for event in tool.events if event[0] == "write"]) == no_write_after
    assert ("reset", 2) not in tool.events
    assert "synthetic private verification error" not in capsys.readouterr().out


def test_missing_record_never_loads_esptool_or_checks_port(review, monkeypatch):
    paths, _, approval = review
    approval.unlink()

    def never(*_):
        pytest.fail("device prerequisites invoked without scoped approval")

    monkeypatch.setattr(rom, "_load_esptool", never)
    assert rom.run_rom_paid_trial(paths, "mock-port", never, never).approval_rejected
