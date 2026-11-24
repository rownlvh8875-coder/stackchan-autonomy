"""Order the steps for an authorized K151 paid trial and rollback.

The caller owns the reviewed file hashes, durable one-time claim, serial
transport, user interaction and time limits. This module has no device
adapter, CLI, credential access or API client.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class TrialStep(StrEnum):
    PREFLIGHT = "preflight"
    CLAIM_ONCE = "claim_once"
    WRITE_APP = "write_app"
    VERIFY_APP = "verify_app"
    RECORD_TRIAL_BOOT_INTENT = "record_trial_boot_intent"
    BOOT_AND_RUN_ONE_TURN = "boot_and_run_one_turn"
    REBIND_FOR_RESTORE = "rebind_for_restore"
    WRITE_ORIGINAL_OTA1 = "write_original_ota1"
    VERIFY_ORIGINAL_OTA1 = "verify_original_ota1"
    WRITE_PRETRIAL_NVS = "write_pretrial_nvs"
    VERIFY_PRETRIAL_NVS = "verify_pretrial_nvs"
    VERIFY_FACTORY_METADATA = "verify_factory_metadata"
    RECORD_FACTORY_BOOT_INTENT = "record_factory_boot_intent"
    REQUEST_FACTORY_BOOT = "request_factory_boot"
    RECORD_RECOVERY_COMPLETE = "record_recovery_complete"


@dataclass(frozen=True)
class TrialScopes:
    """Separate scope checks already bound to the same reviewed device and files."""

    install_and_restore_ota1: bool = False
    one_paid_turn: bool = False
    restore_nvs: bool = False

    @property
    def complete(self) -> bool:
        return all(
            scope is True
            for scope in (self.install_and_restore_ota1, self.one_paid_turn, self.restore_nvs)
        )


@dataclass(frozen=True)
class TrialResult:
    approval_rejected: bool = False
    install_attempted: bool = False
    trial_failure: TrialStep | None = None
    recovery_failure: TrialStep | None = None

    @property
    def factory_boot_requested(self) -> bool:
        """The backend confirmed the reset request; the LCD still needs checking."""
        return self.install_attempted and self.recovery_failure in (
            None,
            TrialStep.RECORD_RECOVERY_COMPLETE,
        )


def _first_failed(
    perform: Callable[[TrialStep], bool], steps: tuple[TrialStep, ...]
) -> TrialStep | None:
    for step in steps:
        try:
            if perform(step) is True:
                continue
        except (Exception, KeyboardInterrupt, SystemExit):
            # The private backend may have paths or credential data in an error.
            # Expose only the fixed phase, including when the outcome is uncertain.
            pass
        return step
    return None


def _restore(
    perform: Callable[[TrialStep], bool], *, trial_boot_possible: bool, factory_boot_possible: bool
) -> TrialStep | None:
    # A factory boot may already have legitimately changed NVS. In that state
    # allow verification only, even if an original-range comparison now fails.
    restore_ota = () if factory_boot_possible else (TrialStep.WRITE_ORIGINAL_OTA1,)
    restore_nvs = (
        (TrialStep.WRITE_PRETRIAL_NVS,) if trial_boot_possible and not factory_boot_possible else ()
    )
    record_factory_boot = () if factory_boot_possible else (TrialStep.RECORD_FACTORY_BOOT_INTENT,)
    return _first_failed(
        perform,
        (
            TrialStep.REBIND_FOR_RESTORE,
            *restore_ota,
            TrialStep.VERIFY_ORIGINAL_OTA1,
            *restore_nvs,
            TrialStep.VERIFY_PRETRIAL_NVS,
            TrialStep.VERIFY_FACTORY_METADATA,
            *record_factory_boot,
            TrialStep.REQUEST_FACTORY_BOOT,
            TrialStep.RECORD_RECOVERY_COMPLETE,
        ),
    )


def recover_paid_trial(
    perform: Callable[[TrialStep], bool], *, trial_boot_possible: bool, factory_boot_possible: bool
) -> TrialResult:
    """Resume only recovery after the caller validates the durable phase record."""
    return TrialResult(
        install_attempted=True,
        recovery_failure=_restore(
            perform,
            trial_boot_possible=trial_boot_possible,
            factory_boot_possible=factory_boot_possible,
        ),
    )


def run_paid_trial(scopes: TrialScopes, perform: Callable[[TrialStep], bool]) -> TrialResult:
    """Run once. A failed write may have changed flash, so recover from that point.

    PREFLIGHT verifies the bound board, current layout, OTA data, and both
    original ranges. CLAIM_ONCE durably consumes the scoped authorization.
    Before BOOT_AND_RUN_ONE_TURN, all commands must leave the board in ROM.
    REBIND_FOR_RESTORE re-verifies identity and immutable metadata before
    writing, even if the board or the serial connection reset during the trial.
    """
    if not scopes.complete:
        return TrialResult(approval_rejected=True)
    failure = _first_failed(perform, (TrialStep.PREFLIGHT, TrialStep.CLAIM_ONCE))
    if failure is not None:
        return TrialResult(trial_failure=failure)

    trial_boot_possible = False
    try:
        failure = _first_failed(
            perform, (TrialStep.WRITE_APP, TrialStep.VERIFY_APP, TrialStep.RECORD_TRIAL_BOOT_INTENT)
        )
        if failure is None:
            # A boot request can take effect even when the transport then fails.
            trial_boot_possible = True
            failure = _first_failed(perform, (TrialStep.BOOT_AND_RUN_ONE_TURN,))
    finally:
        recovery_failure = _restore(
            perform, trial_boot_possible=trial_boot_possible, factory_boot_possible=False
        )
    return TrialResult(
        install_attempted=True, trial_failure=failure, recovery_failure=recovery_failure
    )
