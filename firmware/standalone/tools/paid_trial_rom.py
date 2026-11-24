"""Connect an already-scoped K151 trial to esptool in a dedicated process.

There is no executable entry point. The caller supplies the reviewed port
check and the bounded owner-led conversation after the USB port is closed.
"""

import hashlib
import io
import re
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout, suppress

from esp_app_image import (
    NVS_OFFSET,
    OTADATA_BYTES,
    OTADATA_OFFSET,
    PARTITION_TABLE_BYTES,
    PARTITION_TABLE_OFFSET,
    SLOT_OFFSET,
)
from paid_trial_binding import BoundPaidTrial, PaidTrialPaths, run_bound_paid_trial
from paid_trial_sequence import TrialResult, TrialStep

_KEEP = {"flash_mode": "keep", "flash_freq": "keep", "flash_size": "keep"}


def _load_esptool():
    import esptool
    from esp_pylib.logger import EspLog
    from esptool import cmds
    from esptool.targets import ESP32S3ROM

    if esptool.__version__ != "5.6.0":
        raise ValueError("unreviewed esptool version")
    # A pre-existing Rich console can retain its original output streams.
    EspLog().set_console_options(quiet=True)
    return esptool.detect_chip, ESP32S3ROM, cmds


class _RomPaidTrial:
    def __init__(self, port, port_available, exercise_one_turn):
        self.port = port
        self.port_available = port_available
        self.exercise_one_turn = exercise_one_turn
        self.esptool = None
        self.chip = None

    def close(self):
        chip, self.chip = self.chip, None
        if chip is not None:
            chip._port.close()

    def _open_bound(self, files):
        identities = re.findall(
            r"^\s*MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})[ \t]*$",
            files.board_reference.decode("utf-8-sig"),
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if len(identities) != 1:
            raise ValueError("missing or ambiguous reviewed board identity")
        expected_mac = tuple(bytes.fromhex(identities[0].replace(":", "")))

        self.close()
        if self.port_available(self.port) is not True:
            raise ValueError("reviewed port unavailable")
        if self.esptool is None:
            self.esptool = _load_esptool()
        detect_chip, rom_type, self.cmds = self.esptool
        self.chip = chip = detect_chip(self.port, connect_mode="default-reset", connect_attempts=1)
        if (
            type(chip) is not rom_type
            or chip.IS_STUB
            or chip.secure_download_mode
            or chip.get_chip_revision() != 2
            or chip.read_mac() != expected_mac
            or chip.get_secure_boot_enabled()
            or chip.get_flash_encryption_enabled()
        ):
            raise ValueError("current ROM identity or security differs")
        self.cmds.attach_flash(chip)
        if self.cmds.detect_flash_size(chip) != "16MB":
            raise ValueError("physical flash capacity differs")
        self._check_factory_metadata(files)

    def _check_factory_metadata(self, files):
        for offset, size, digest in (
            (PARTITION_TABLE_OFFSET, PARTITION_TABLE_BYTES, files.factory_table_sha256),
            (OTADATA_OFFSET, OTADATA_BYTES, files.factory_otadata_sha256),
        ):
            data = self.cmds.read_flash(self.chip, offset, size, no_progress=True)
            if (
                not isinstance(data, bytes)
                or len(data) != size
                or hashlib.sha256(data).hexdigest() != digest
            ):
                raise ValueError("current partition table or OTA metadata differs")

    def _verify(self, offset, data):
        self.cmds.verify_flash(self.chip, [(offset, data)], **_KEEP, diff=False)

    def _write(self, offset, data):
        self.cmds.write_flash(
            self.chip,
            [(offset, data)],
            **_KEEP,
            erase_all=False,
            encrypt=False,
            force=False,
        )

    def _reset_and_release(self):
        try:
            self.cmds.reset_chip(self.chip, "hard-reset")
        finally:
            self.close()

    def __call__(self, step: TrialStep, files: BoundPaidTrial) -> bool:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            match step:
                case TrialStep.PREFLIGHT:
                    self._open_bound(files)
                    self._verify(SLOT_OFFSET, files.ota1)
                    self._verify(NVS_OFFSET, files.nvs)
                case TrialStep.WRITE_APP:
                    self._write(SLOT_OFFSET, files.app)
                case TrialStep.VERIFY_APP:
                    self._verify(SLOT_OFFSET, files.app)
                case TrialStep.BOOT_AND_RUN_ONE_TURN | TrialStep.REQUEST_FACTORY_BOOT:
                    self._reset_and_release()
                case TrialStep.REBIND_FOR_RESTORE:
                    self._open_bound(files)
                case TrialStep.WRITE_ORIGINAL_OTA1:
                    self._write(SLOT_OFFSET, files.ota1)
                case TrialStep.VERIFY_ORIGINAL_OTA1:
                    self._verify(SLOT_OFFSET, files.ota1)
                case TrialStep.WRITE_PRETRIAL_NVS:
                    self._write(NVS_OFFSET, files.nvs)
                case TrialStep.VERIFY_PRETRIAL_NVS:
                    self._verify(NVS_OFFSET, files.nvs)
                case TrialStep.VERIFY_FACTORY_METADATA:
                    self._check_factory_metadata(files)
                case _:
                    return False
        if step is TrialStep.BOOT_AND_RUN_ONE_TURN:
            return self.exercise_one_turn is not None and self.exercise_one_turn() is True
        return True


def run_rom_paid_trial(
    paths: PaidTrialPaths,
    port: str,
    port_available: Callable[[str], bool],
    exercise_one_turn: Callable[[], bool] | None,
    *,
    recover_only: bool = False,
) -> TrialResult:
    adapter = _RomPaidTrial(port, port_available, exercise_one_turn)
    try:
        return run_bound_paid_trial(paths, adapter, port=port, recover_only=recover_only)
    finally:
        with suppress(OSError):
            adapter.close()
