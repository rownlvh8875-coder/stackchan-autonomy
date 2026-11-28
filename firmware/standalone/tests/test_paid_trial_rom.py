"""Rehearse the reviewed ROM adapter with ESP32-S3 and esptool doubles."""

import hashlib
import json
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
        if (self.owner.wrong_preflight_board and self.index == 1) or (
            self.owner.wrong_recovery_board and self.index == 2
        ):
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
        self.wrong_preflight_board = False
        self.wrong_recovery_board = False
        self.bad_metadata = False
        self.bad_final_metadata = False
        self.fail_ota_restore = False
        self.preflight_nvs_error = None
        self.preflight_reset_error = None
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
        if chip.index == 1 and address == 0x9000 and self.preflight_nvs_error is not None:
            raise self.preflight_nvs_error("synthetic private preflight error")
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
        if chip.index == 1 and self.preflight_reset_error is not None:
            raise self.preflight_reset_error("synthetic private reset error")


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


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_verified_ranges_survive_failed_turn_with_usb_closed_during_turn(
    review, monkeypatch, newline
):
    paths, _, approval = review
    reference = paths.board_reference.read_bytes().replace(b"\n", newline)
    paths.board_reference.write_bytes(reference)
    scope = json.loads(approval.read_bytes())
    scope["board_reference_sha256"] = hashlib.sha256(reference).hexdigest()
    approval.write_text(json.dumps(scope), encoding="utf-8")
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
    "reference",
    [
        b"MAC:\n02:00:00:00:00:01\n",
        b"MAC: 02:00:00:00:00:01\r\nMAC: 02:00:00:00:00:01\r\n",
    ],
)
def test_ambiguous_board_reference_does_not_open_port(review, monkeypatch, reference):
    paths, _, approval = review
    paths.board_reference.write_bytes(reference)
    scope = json.loads(approval.read_bytes())
    scope["board_reference_sha256"] = hashlib.sha256(reference).hexdigest()
    approval.write_text(json.dumps(scope), encoding="utf-8")
    result, tool, _ = run(review, monkeypatch)
    assert result.trial_failure is TrialStep.PREFLIGHT
    assert tool.events == []


@pytest.mark.parametrize(
    ("attribute", "failure", "no_write_after"),
    [
        ("wrong_preflight_board", TrialStep.PREFLIGHT, 0),
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
    if failure is TrialStep.PREFLIGHT:
        assert ("reset", 1) not in tool.events
    assert ("reset", 2) not in tool.events
    assert "synthetic private verification error" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("nvs_error", "reset_error", "status"),
    [
        (ValueError, None, "requested"),
        (KeyboardInterrupt, None, "requested"),
        (ValueError, OSError, "unconfirmed"),
        (ValueError, KeyboardInterrupt, "unconfirmed"),
    ],
)
def test_preflight_nvs_rejection_returns_verified_factory_app_to_normal_boot(
    review, monkeypatch, capsys, nvs_error, reset_error, status
):
    def command_setup(tool):
        tool.preflight_nvs_error = nvs_error
        tool.preflight_reset_error = reset_error

    result, tool, paths = run(review, monkeypatch, command_setup)
    assert result.trial_failure is TrialStep.PREFLIGHT
    assert not result.install_attempted and not result.factory_boot_requested
    assert result.recovery_failure is None
    assert tool.events[-4:] == [
        ("verify", 1, 0x510000),
        ("verify", 1, 0x9000),
        ("reset", 1),
        ("close", 1),
    ]
    assert result.preflight_factory_boot == status
    assert not (paths.review_dir / "install-started.json").exists()
    assert not any(event[0] in {"write", "trial"} for event in tool.events)
    captured = capsys.readouterr()
    assert "synthetic private" not in captured.out + captured.err


def test_preflight_does_not_boot_unverified_factory_app(review, monkeypatch):
    def command_setup(tool):
        tool.flash[0x510000] = b"synthetic different factory app"

    result, tool, _ = run(review, monkeypatch, command_setup)
    assert result.trial_failure is TrialStep.PREFLIGHT
    assert not result.install_attempted
    assert not any(event[0] in {"write", "trial", "reset"} for event in tool.events)


@pytest.mark.parametrize("journal_exists", [False, True])
def test_no_write_claim_failure_only_reboots_without_install_journal(
    review, monkeypatch, journal_exists
):
    paths, _, approval = review
    journal = paths.review_dir / "install-started.json"

    def command_setup(tool):
        verify_flash = tool.verify_flash

        def change_review(chip, regions, **kwargs):
            verify_flash(chip, regions, **kwargs)
            if regions[0][0] == 0x9000:
                if journal_exists:
                    journal.write_bytes(b"fixture uncertain install journal")
                else:
                    approval.write_bytes(approval.read_bytes() + b"\n")

        tool.verify_flash = change_review

    result, tool, _ = run(review, monkeypatch, command_setup)
    assert result.trial_failure is TrialStep.CLAIM_ONCE
    assert not result.install_attempted and result.recovery_failure is None
    assert (("reset", 1) in tool.events) is not journal_exists
    assert result.preflight_factory_boot == (None if journal_exists else "requested")
    assert tool.events[-1] == ("close", 1)
    assert not any(event[0] in {"write", "trial"} for event in tool.events)


def test_missing_record_never_loads_esptool_or_checks_port(review, monkeypatch):
    paths, _, approval = review
    approval.unlink()

    def never(*_):
        pytest.fail("device prerequisites invoked without scoped approval")

    monkeypatch.setattr(rom, "_load_esptool", never)
    assert rom.run_rom_paid_trial(paths, "mock-port", never, never).approval_rejected
