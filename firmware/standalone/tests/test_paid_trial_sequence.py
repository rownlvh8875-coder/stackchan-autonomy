"""Model the device steps with a fake backend. No USB, NVS or OpenAI calls."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from paid_trial_sequence import TrialScopes, TrialStep, run_paid_trial  # noqa: E402

SCOPES = TrialScopes(install_and_restore_ota1=True, one_paid_turn=True, restore_nvs=True)
INSTALL = (
    TrialStep.PREFLIGHT,
    TrialStep.CLAIM_ONCE,
    TrialStep.WRITE_APP,
    TrialStep.VERIFY_APP,
    TrialStep.BOOT_AND_RUN_ONE_TURN,
)
RECOVER = (
    TrialStep.REBIND_FOR_RESTORE,
    TrialStep.WRITE_ORIGINAL_OTA1,
    TrialStep.VERIFY_ORIGINAL_OTA1,
    TrialStep.WRITE_PRETRIAL_NVS,
    TrialStep.VERIFY_PRETRIAL_NVS,
    TrialStep.VERIFY_FACTORY_METADATA,
    TrialStep.REQUEST_FACTORY_BOOT,
)


class FakeRunner:
    def __init__(self, *failures, claim_file=None):
        self.failures = set(failures)
        self.steps = []
        self.claim_file = claim_file

    def __call__(self, step):
        self.steps.append(step)
        if step in self.failures:
            return False
        if step == TrialStep.CLAIM_ONCE and self.claim_file is not None:
            try:
                with self.claim_file.open("x", encoding="ascii") as record:
                    record.write("synthetic claim")
            except FileExistsError:
                return False
        return True


@pytest.mark.parametrize(
    "scopes",
    [
        TrialScopes(False, True, True),
        TrialScopes(True, False, True),
        TrialScopes(True, True, False),
        TrialScopes(True, True, "false"),
    ],
)
def test_incomplete_scope_never_invokes_backend(scopes):
    runner = FakeRunner()
    result = run_paid_trial(scopes, runner)
    assert result.approval_rejected and not result.install_attempted
    assert runner.steps == []


@pytest.mark.parametrize("failed", INSTALL[:2])
def test_preflight_and_claim_failure_never_write(failed):
    runner = FakeRunner(failed)
    result = run_paid_trial(SCOPES, runner)
    assert result.trial_failure is failed and not result.install_attempted
    assert runner.steps == list(INSTALL[: INSTALL.index(failed) + 1])


def test_one_turn_restores_both_ranges_and_a_claim_cannot_be_replayed(tmp_path):
    claim_file = tmp_path / "claim"
    runner = FakeRunner(claim_file=claim_file)
    result = run_paid_trial(SCOPES, runner)
    assert result.trial_failure is None and result.recovery_failure is None
    assert result.install_attempted and result.factory_boot_requested
    assert runner.steps == [*INSTALL, *RECOVER]
    runner = FakeRunner(claim_file=claim_file)
    replay = run_paid_trial(SCOPES, runner)
    assert replay.trial_failure is TrialStep.CLAIM_ONCE and not replay.install_attempted
    assert runner.steps == list(INSTALL[:2])


@pytest.mark.parametrize("failed", INSTALL[2:])
def test_install_attempt_failure_recovers_in_order(failed):
    runner = FakeRunner(failed)
    result = run_paid_trial(SCOPES, runner)
    assert result.trial_failure is failed
    assert result.factory_boot_requested and result.recovery_failure is None
    after = list(RECOVER)
    if failed is not TrialStep.BOOT_AND_RUN_ONE_TURN:
        after.remove(TrialStep.WRITE_PRETRIAL_NVS)
    assert runner.steps == [*INSTALL[: INSTALL.index(failed) + 1], *after]


@pytest.mark.parametrize("failed", RECOVER)
def test_failed_recovery_never_advances_to_the_next_range_or_boot(failed):
    runner = FakeRunner(TrialStep.BOOT_AND_RUN_ONE_TURN, failed)
    result = run_paid_trial(SCOPES, runner)
    assert result.trial_failure is TrialStep.BOOT_AND_RUN_ONE_TURN
    assert result.recovery_failure is failed and not result.factory_boot_requested
    assert runner.steps == [*INSTALL, *RECOVER[: RECOVER.index(failed) + 1]]


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_trial_exception_or_abort_recovers_without_reporting_exception_text(failure):
    runner = FakeRunner()

    def attempt(step):
        if step is TrialStep.BOOT_AND_RUN_ONE_TURN:
            runner.steps.append(step)
            raise failure("synthetic privacy sentinel")
        return runner(step)

    result = run_paid_trial(SCOPES, attempt)
    assert result.trial_failure is TrialStep.BOOT_AND_RUN_ONE_TURN
    assert "synthetic privacy sentinel" not in repr(result)
    assert result.factory_boot_requested
    assert runner.steps == [*INSTALL, *RECOVER]
