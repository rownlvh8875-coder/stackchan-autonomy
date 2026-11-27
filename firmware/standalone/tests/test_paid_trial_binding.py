"""Test the local approval/artifact binding with no device backend."""

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from paid_trial_binding import PaidTrialPaths  # noqa: E402
from paid_trial_binding import run_bound_paid_trial as run_bound  # noqa: E402
from paid_trial_sequence import TrialStep  # noqa: E402


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_bound_paid_trial(paths, perform, *, port="COM3", recover_only=False):
    return run_bound(paths, perform, port=port, recover_only=recover_only)


@pytest.fixture
def review(tmp_path, monkeypatch):
    monkeypatch.setattr("paid_trial_binding.gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    paths = PaidTrialPaths(
        review_dir=tmp_path,
        app=tmp_path / "app.bin",
        ota1=tmp_path / "ota1.bin",
        nvs=tmp_path / "nvs.bin",
        board_reference=tmp_path / "reference.txt",
    )
    app, ota1, nvs = b"synthetic app", b"a" * 0x4F0000, b"n" * 0x4000
    for path, data in ((paths.app, app), (paths.ota1, ota1), (paths.nvs, nvs)):
        path.write_bytes(data)
    paths.board_reference.write_bytes(
        b"synthetic private board reference\nMAC: 02:00:00:00:00:01\n"
    )
    manifest = {
        "kind": "LOCAL_ONE_PAID_TURN_REVIEW",
        "private_board_policy_embedded": True,
        "install_authorized": False,
        "runtime_budget_write_scope": "sc_gpt/budget",
        "write_offset": 0x510000,
        "write_bytes": len(app),
        "erase_span_bytes": 4096,
        "image_sha256": digest(app),
        "recovery": {
            "restore_authorized": False,
            "factory_table_sha256": digest(b"m" * 0x1000),
            "factory_otadata_sha256": digest(b"m" * 0x2000),
            "restore_in_order": [
                {
                    "partition": "ota_1",
                    "offset": 0x510000,
                    "bytes": len(ota1),
                    "sha256": digest(ota1),
                },
                {"partition": "nvs", "offset": 0x9000, "bytes": len(nvs), "sha256": digest(nvs)},
            ],
        },
    }
    review_path = tmp_path / "review-manifest.json"
    review_path.write_text(json.dumps(manifest), encoding="utf-8")
    approve_path = tmp_path / "approval.json"
    approve_path.write_text(
        json.dumps(
            {
                "review_sha256": digest(review_path.read_bytes()),
                "board_reference_sha256": digest(paths.board_reference.read_bytes()),
                "install_and_restore_ota1": True,
                "one_paid_turn": True,
                "restore_nvs": True,
            }
        ),
        encoding="utf-8",
    )
    return paths, review_path, approve_path


@pytest.mark.parametrize("missing", ["install_and_restore_ota1", "one_paid_turn", "restore_nvs"])
def test_separate_approval_required_before_using_backend(review, missing):
    paths, _, approval = review
    record = json.loads(approval.read_bytes())
    record[missing] = "true"
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert run_bound_paid_trial(paths, lambda *_: pytest.fail("opened backend")).approval_rejected


@pytest.mark.parametrize("which", ["app", "ota1", "nvs", "board_reference", "manifest"])
def test_changed_input_stops_before_any_backend_step(review, which):
    paths, manifest, _ = review
    path = manifest if which == "manifest" else getattr(paths, which)
    with path.open("r+b") as handle:
        handle.write(b"X")
    assert run_bound_paid_trial(paths, lambda *_: pytest.fail("opened backend")).approval_rejected


def test_restore_order_must_be_safe_even_if_someone_approved_the_review_bytes(review):
    paths, manifest, approval = review
    details = json.loads(manifest.read_bytes())
    details["recovery"]["restore_in_order"].reverse()
    manifest.write_text(json.dumps(details), encoding="utf-8")
    record = json.loads(approval.read_bytes())
    record["review_sha256"] = digest(manifest.read_bytes())
    approval.write_text(json.dumps(record), encoding="utf-8")
    assert run_bound_paid_trial(paths, lambda *_: pytest.fail("opened backend")).approval_rejected


def test_claim_is_durable_before_write_and_keeps_verified_bytes(review):
    paths, _, _ = review
    claim = paths.review_dir / "install-started.json"
    seen = []

    def perform(step, bind):
        seen.append(step)
        assert "synthetic private board reference" not in repr(bind)
        if step is TrialStep.PREFLIGHT:
            assert not claim.exists()
            paths.app.write_bytes(b"after verification change")
        if step is TrialStep.WRITE_APP:
            assert claim.is_file()
            assert bind.app == b"synthetic app"
        return True

    assert run_bound_paid_trial(paths, perform).factory_boot_requested
    assert TrialStep.CLAIM_ONCE not in seen
    assert seen.index(TrialStep.VERIFY_ORIGINAL_OTA1) < seen.index(TrialStep.WRITE_PRETRIAL_NVS)
    paths.app.write_bytes(b"synthetic app")
    assert not run_bound_paid_trial(paths, lambda *_: pytest.fail("replayed")).install_attempted


def test_competing_claim_between_preflight_and_install_blocks_the_write(review):
    paths, _, _ = review

    def perform(step, _bind):
        assert step is TrialStep.PREFLIGHT
        (paths.review_dir / "install-started.json").write_bytes(b"another process")
        return True

    result = run_bound_paid_trial(paths, perform)
    assert result.trial_failure is TrialStep.CLAIM_ONCE
    assert not result.install_attempted


def test_scope_changed_during_preflight_cannot_be_consumed(review):
    paths, _, approval = review

    def perform(step, _bind):
        assert step is TrialStep.PREFLIGHT
        approval.write_text("{}", encoding="utf-8")
        return True

    result = run_bound_paid_trial(paths, perform)
    assert result.trial_failure is TrialStep.CLAIM_ONCE
    assert not result.install_attempted
    assert not (paths.review_dir / "install-started.json").exists()


@pytest.mark.parametrize(
    ("interrupt_at", "expected_writes"),
    [
        (TrialStep.WRITE_APP, [TrialStep.WRITE_ORIGINAL_OTA1]),
        (
            TrialStep.BOOT_AND_RUN_ONE_TURN,
            [TrialStep.WRITE_ORIGINAL_OTA1, TrialStep.WRITE_PRETRIAL_NVS],
        ),
        (TrialStep.REQUEST_FACTORY_BOOT, []),
    ],
)
def test_recovery_uses_only_the_ranges_allowed_at_the_interrupted_phase(
    review, interrupt_at, expected_writes
):
    paths, _, _ = review
    interrupted = False

    def first_run(step, _inputs):
        nonlocal interrupted
        interrupted |= step is interrupt_at
        return not interrupted

    result = run_bound_paid_trial(paths, first_run)
    assert result.recovery_failure is not None
    seen = []

    def restore(step, _inputs):
        seen.append(step)
        return True

    result = run_bound_paid_trial(paths, restore, recover_only=True)
    assert result.factory_boot_requested and result.trial_failure is None
    assert seen == [
        TrialStep.REBIND_FOR_RESTORE,
        *(
            [TrialStep.WRITE_ORIGINAL_OTA1]
            if TrialStep.WRITE_ORIGINAL_OTA1 in expected_writes
            else []
        ),
        TrialStep.VERIFY_ORIGINAL_OTA1,
        *(
            [TrialStep.WRITE_PRETRIAL_NVS]
            if TrialStep.WRITE_PRETRIAL_NVS in expected_writes
            else []
        ),
        TrialStep.VERIFY_PRETRIAL_NVS,
        TrialStep.VERIFY_FACTORY_METADATA,
        TrialStep.REQUEST_FACTORY_BOOT,
    ]
    seen.clear()
    assert not run_bound_paid_trial(paths, restore, recover_only=True).install_attempted
    assert seen == []


def test_recovery_can_resume_after_a_failed_reconnect(review):
    paths, _, _ = review
    claim = paths.review_dir / "install-started.json"
    result = run_bound_paid_trial(
        paths,
        lambda step, _: step not in (TrialStep.BOOT_AND_RUN_ONE_TURN, TrialStep.REBIND_FOR_RESTORE),
    )
    assert result.recovery_failure is TrialStep.REBIND_FOR_RESTORE
    journal = claim.read_bytes()
    seen = []

    def reconnect_fails(step, _inputs):
        seen.append(step)
        return False

    result = run_bound_paid_trial(paths, reconnect_fails, recover_only=True)
    assert result.recovery_failure is TrialStep.REBIND_FOR_RESTORE
    assert seen == [TrialStep.REBIND_FOR_RESTORE] and claim.read_bytes() == journal

    def restore(step, _inputs):
        seen.append(step)
        return True

    seen.clear()
    result = run_bound_paid_trial(paths, restore, recover_only=True)
    assert result.factory_boot_requested and result.recovery_failure is None
    assert TrialStep.WRITE_APP not in seen and TrialStep.BOOT_AND_RUN_ONE_TURN not in seen
    assert TrialStep.WRITE_ORIGINAL_OTA1 in seen and TrialStep.WRITE_PRETRIAL_NVS in seen


@pytest.mark.parametrize("change", ["missing", "port", "approval", "torn", "in_use", "old"])
def test_unsafe_resume_stops_before_device_contact(review, change):
    paths, _, approval = review
    claim = paths.review_dir / "install-started.json"
    seen = []

    def restore(step, _inputs):
        seen.append(step)
        return True

    def first_run(step, _inputs):
        if step is TrialStep.BOOT_AND_RUN_ONE_TURN and change == "in_use":
            assert not run_bound_paid_trial(paths, restore, recover_only=True).install_attempted
        return step not in (TrialStep.BOOT_AND_RUN_ONE_TURN, TrialStep.REBIND_FOR_RESTORE)

    if change not in ("missing", "old"):
        assert run_bound_paid_trial(paths, first_run).install_attempted
    if change == "in_use":
        assert seen == []
        return
    if change == "approval":
        approval.write_bytes(approval.read_bytes() + b" ")
    if change == "torn":
        claim.write_bytes(claim.read_bytes()[:-1])
    if change == "old":
        claim.write_text(
            json.dumps({"review_sha256": digest(review[1].read_bytes())}), encoding="utf-8"
        )
    result = run_bound_paid_trial(
        paths, restore, port="COM4" if change == "port" else "COM3", recover_only=True
    )
    assert not result.install_attempted
    assert seen == []


def test_process_exit_releases_lock_and_preserves_trial_boot_intent(review):
    paths, _, _ = review
    child = """
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from paid_trial_binding import PaidTrialPaths, run_bound_paid_trial
from paid_trial_sequence import TrialStep

def interrupt(step, _inputs):
    if step is TrialStep.BOOT_AND_RUN_ONE_TURN:
        os._exit(17)
    return True

run_bound_paid_trial(PaidTrialPaths(*map(Path, sys.argv[2:])), interrupt, port='COM3')
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(Path(__file__).resolve().parents[1] / "tools"),
            *map(str, (paths.review_dir, paths.app, paths.ota1, paths.nvs, paths.board_reference)),
        ],
        check=False,
        timeout=10,
    )
    assert process.returncode == 17
    seen = []

    def restore(step, _inputs):
        seen.append(step)
        return True

    result = run_bound_paid_trial(paths, restore, recover_only=True)
    assert result.factory_boot_requested
    assert seen[0] is TrialStep.REBIND_FOR_RESTORE
    assert seen[-1] is TrialStep.REQUEST_FACTORY_BOOT
    assert TrialStep.WRITE_PRETRIAL_NVS in seen
    assert TrialStep.BOOT_AND_RUN_ONE_TURN not in seen


def test_another_review_directory_cannot_open_the_same_port_during_a_trial(review):
    paths, manifest, approval = review
    alternate = replace(paths, review_dir=paths.review_dir / "other-review")
    alternate.review_dir.mkdir()
    for source in (manifest, approval):
        (alternate.review_dir / source.name).write_bytes(source.read_bytes())
    observed = []

    def perform(step, _inputs):
        if step is TrialStep.BOOT_AND_RUN_ONE_TURN:
            result = run_bound_paid_trial(alternate, lambda nested, _: observed.append(nested))
            assert result.trial_failure is TrialStep.CLAIM_ONCE
        return True

    result = run_bound_paid_trial(paths, perform)
    assert result.trial_failure is None
    assert observed == []
