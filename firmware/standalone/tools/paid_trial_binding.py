"""Bind a one-turn or reboot K151 trial backend to its local review, consent and files.

The backend still verifies the live board and controls any transport. This
module has no device/API client and never creates an approval record.
"""

import hashlib
import json
import os
import re
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import gettempdir
from typing import BinaryIO

from check_conversation_image import REBOOT_TRIAL_MARKER, verify_reboot_trial_marker
from esp_app_image import NVS_BYTES, NVS_OFFSET, SLOT_BYTES, SLOT_OFFSET
from paid_trial_sequence import (
    REBOOT_TRIAL_BUDGET_KEYS,
    PreflightFactoryBoot,
    TrialResult,
    TrialScopes,
    TrialStep,
    matches_reboot_trial_cap,
    recover_paid_trial,
    run_paid_trial,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_JOURNAL_LIMIT = 4096
_RECORDED_PHASES = (
    TrialStep.RECORD_TRIAL_BOOT_INTENT,
    TrialStep.RECORD_FACTORY_BOOT_INTENT,
    TrialStep.RECORD_RECOVERY_COMPLETE,
)


@dataclass(frozen=True)
class PaidTrialPaths:
    review_dir: Path
    app: Path
    ota1: Path
    nvs: Path
    board_reference: Path


@dataclass(frozen=True)
class BoundPaidTrial:
    # The backend uses these exact bytes, even if a local source path changes.
    app: bytes = field(repr=False)
    ota1: bytes = field(repr=False)
    nvs: bytes = field(repr=False)
    board_reference: bytes = field(repr=False)
    factory_table_sha256: str
    factory_otadata_sha256: str


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ValueError("invalid local trial file size")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_verified(path: Path, size: int, digest: str) -> bytes:
    data = _read_bounded(path, size)
    if len(data) != size or _sha256(data) != digest:
        raise ValueError("trial file does not match local review")
    return data


def _verify_reboot_budget(reviewed: dict, approved: dict, nvs_sha256: str) -> None:
    baseline = reviewed.get("budget_baseline")
    if not isinstance(baseline, dict) or baseline.get("pretrial_nvs_sha256") != nvs_sha256:
        raise ValueError("budget review differs from pretrial NVS")
    missing = baseline.get("trial_budget_must_be_missing")
    digest = baseline["trial_budget_sha256"]
    if (
        type(missing) is not bool
        or approved.get("create_initial_budget") is not missing
        or (missing and digest is not None)
        or (
            not missing
            and (not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest))
        )
    ):
        raise ValueError("budget baseline or initial creation approval differs")


def _bind_files(
    paths: PaidTrialPaths, reviewed: dict, approval: dict, *, reboot_trial: bool
) -> BoundPaidTrial:
    size = reviewed["write_bytes"]
    kind = "LOCAL_REBOOT_PAID_TRIAL_REVIEW" if reboot_trial else "LOCAL_ONE_PAID_TURN_REVIEW"
    budget_scope = list(REBOOT_TRIAL_BUDGET_KEYS) if reboot_trial else "sc_gpt/budget"
    if (
        reviewed.get("kind") != kind
        or reviewed.get("private_board_policy_embedded") is not True
        or reviewed.get("install_authorized") is not False
        or reviewed.get("runtime_budget_write_scope") != budget_scope
        or reviewed.get("write_offset") != SLOT_OFFSET
        or type(size) is not int
        or not 0 < size <= SLOT_BYTES
        or reviewed.get("erase_span_bytes") != (size + 4095) // 4096 * 4096
    ):
        raise ValueError("invalid trial app scope")
    recovery = reviewed["recovery"]
    if not isinstance(recovery, dict) or recovery.get("restore_authorized") is not False:
        raise ValueError("invalid recovery scope")
    table_hash = recovery["factory_table_sha256"]
    otadata_hash = recovery["factory_otadata_sha256"]
    if not all(
        isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest)
        for digest in (table_hash, otadata_hash)
    ):
        raise ValueError("invalid factory metadata digest")
    ranges = recovery["restore_in_order"]
    if not isinstance(ranges, list) or len(ranges) != 2:
        raise ValueError("invalid recovery ranges")
    for item, expected in zip(
        ranges, (("ota_1", SLOT_OFFSET, SLOT_BYTES), ("nvs", NVS_OFFSET, NVS_BYTES))
    ):
        if (
            not isinstance(item, dict)
            or (item.get("partition"), item.get("offset"), item.get("bytes")) != expected
        ):
            raise ValueError("recovery range differs from the reviewed geometry")
    board = _read_bounded(paths.board_reference, 16 * 1024)
    if _sha256(board) != approval.get("board_reference_sha256"):
        raise ValueError("board reference differs from approved reference")
    app = _read_verified(paths.app, size, reviewed["image_sha256"])
    if reboot_trial:
        if (
            not matches_reboot_trial_cap(reviewed.get("reboot_trial_paid_turns"))
            or reviewed.get("runtime_owner_setup_write_scope") != "sc_owner/owner_cfg_v2"
            or reviewed.get("fresh_reboot_state_verified") is not True
        ):
            raise ValueError("invalid reviewed reboot trial scope")
        _verify_reboot_budget(reviewed, approval, ranges[1]["sha256"])
        verify_reboot_trial_marker(app)
    elif REBOOT_TRIAL_MARKER in app:
        raise ValueError("reboot trial image requires its own approval")
    return BoundPaidTrial(
        app=app,
        ota1=_read_verified(paths.ota1, SLOT_BYTES, ranges[0]["sha256"]),
        nvs=_read_verified(paths.nvs, NVS_BYTES, ranges[1]["sha256"]),
        board_reference=board,
        factory_table_sha256=table_hash,
        factory_otadata_sha256=otadata_hash,
    )


def _lock_operator(guard: BinaryIO) -> None:
    # Closing the handle (including process exit) releases the lock. Keep the
    # lock file in place so both operators always lock the same file.
    if os.name == "nt":
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _record(**fields: str) -> bytes:
    return (json.dumps(fields, sort_keys=True) + "\n").encode("ascii")


def _saved_phases(journal: bytes, header: bytes) -> set[TrialStep]:
    rows = journal.splitlines(keepends=True)
    if rows.pop(0) != header:
        raise ValueError("trial claim differs from the reviewed files or port")
    phases = set()
    for phase in _RECORDED_PHASES:
        if rows and rows[0] == _record(phase=phase):
            rows.pop(0)
            phases.add(phase)
    if rows or TrialStep.RECORD_RECOVERY_COMPLETE in phases:
        raise ValueError("trial journal is incomplete, invalid or already recovered")
    return phases


def run_bound_paid_trial(
    paths: PaidTrialPaths,
    perform: Callable[[TrialStep, BoundPaidTrial], bool],
    *,
    port: str,
    recover_only: bool = False,
    reboot_trial: bool = False,
    release_preflight: Callable[[], PreflightFactoryBoot | None] | None = None,
) -> TrialResult:
    claim = paths.review_dir / "install-started.json"
    if claim.exists() != recover_only:
        return TrialResult(trial_failure=TrialStep.CLAIM_ONCE)
    manifest_path = paths.review_dir / "review-manifest.json"
    approval_path = paths.review_dir / "approval.json"
    try:
        document = _read_bounded(manifest_path, 64 * 1024)
        review_sha = _sha256(document)
        approval_document = _read_bounded(approval_path, 64 * 1024)
        approved = json.loads(approval_document)
        if not isinstance(approved, dict) or approved.get("review_sha256") != review_sha:
            return TrialResult(approval_rejected=True)
        scopes = TrialScopes(
            install_and_restore_ota1=approved.get("install_and_restore_ota1") is True,
            one_paid_turn=approved.get("one_paid_turn") is True,
            restore_nvs=approved.get("restore_nvs") is True,
            reboot_paid_trial=matches_reboot_trial_cap(approved.get("reboot_trial_paid_turns")),
        )
        if (
            not scopes.complete(reboot_trial=reboot_trial)
            or (reboot_trial and scopes.one_paid_turn)
            or (not reboot_trial and "reboot_trial_paid_turns" in approved)
        ):
            return TrialResult(approval_rejected=True)
        reviewed = json.loads(document)
        if not isinstance(reviewed, dict):
            return TrialResult(approval_rejected=True)
        inputs = _bind_files(paths, reviewed, approved, reboot_trial=reboot_trial)
    except (OSError, KeyError, ValueError, TypeError):
        return TrialResult(approval_rejected=True)

    header = _record(
        review_sha256=review_sha, approval_sha256=_sha256(approval_document), port=port
    )
    journal = b""

    def unchanged_review() -> bool:
        return (
            _read_bounded(approval_path, 64 * 1024) == approval_document
            and _read_bounded(manifest_path, 64 * 1024) == document
        )

    def step_for_review(step: TrialStep) -> bool:
        nonlocal journal
        if step is TrialStep.CLAIM_ONCE:
            if not unchanged_review():
                return False
            with claim.open("xb") as stream:
                stream.write(header)
                stream.flush()
                os.fsync(stream.fileno())
            journal = header
            return True
        if step in _RECORDED_PHASES:
            row = _record(phase=step)
            with claim.open("r+b") as stream:
                if stream.read(_JOURNAL_LIMIT + 1) != journal:
                    return False
                stream.write(row)
                stream.flush()
                os.fsync(stream.fileno())
            journal += row
            return True
        return perform(step, inputs)

    # The port guard also applies to another review directory while the robot's
    # USB cable is disconnected and a serial handle cannot protect the trial.
    port_key = _sha256(port.casefold().encode("utf-8"))
    with ExitStack() as guards:
        try:
            port_guard = Path(gettempdir()) / f"stackchan-paid-trial-{port_key}.lock"
            for lock_path in (paths.review_dir / "operator.lock", port_guard):
                _lock_operator(guards.enter_context(lock_path.open("a+b")))
            if claim.exists() != recover_only or not unchanged_review():
                return TrialResult(trial_failure=TrialStep.CLAIM_ONCE)
            if recover_only:
                journal = _read_bounded(claim, _JOURNAL_LIMIT)
                phases = _saved_phases(journal, header)
        except (OSError, ValueError):
            return TrialResult(trial_failure=TrialStep.CLAIM_ONCE)
        if recover_only:
            return recover_paid_trial(
                step_for_review,
                trial_boot_possible=TrialStep.RECORD_TRIAL_BOOT_INTENT in phases,
                factory_boot_possible=TrialStep.RECORD_FACTORY_BOOT_INTENT in phases,
            )
        result = run_paid_trial(scopes, step_for_review, reboot_trial=reboot_trial)
        # Keep both locks through the same-handle return to factory boot.
        # An existing or partial journal belongs to the recovery path.
        if (
            release_preflight is not None
            and not result.install_attempted
            and result.trial_failure in (TrialStep.PREFLIGHT, TrialStep.CLAIM_ONCE)
            and not claim.exists()
        ):
            return replace(result, preflight_factory_boot=release_preflight())
        return result
