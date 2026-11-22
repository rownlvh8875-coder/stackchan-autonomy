"""Test the local approval/artifact binding with no device backend."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from paid_trial_binding import PaidTrialPaths, run_bound_paid_trial  # noqa: E402
from paid_trial_sequence import TrialStep  # noqa: E402


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def review(tmp_path):
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
    paths.board_reference.write_bytes(b"synthetic private board reference")
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
