"""Bind a K151 one-turn trial backend to its local review, consent and files.

The backend still verifies the live board and controls any transport. This
module has no device/API client and never creates an approval record.
"""

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from esp_app_image import NVS_BYTES, NVS_OFFSET, SLOT_BYTES, SLOT_OFFSET
from paid_trial_sequence import TrialResult, TrialScopes, TrialStep, run_paid_trial


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


def _bind_files(paths: PaidTrialPaths, reviewed: dict, approval: dict) -> BoundPaidTrial:
    size = reviewed["write_bytes"]
    if (
        reviewed.get("kind") != "LOCAL_ONE_PAID_TURN_REVIEW"
        or reviewed.get("private_board_policy_embedded") is not True
        or reviewed.get("install_authorized") is not False
        or reviewed.get("runtime_budget_write_scope") != "sc_gpt/budget"
        or reviewed.get("write_offset") != SLOT_OFFSET
        or type(size) is not int
        or not 0 < size <= SLOT_BYTES
        or reviewed.get("erase_span_bytes") != (size + 4095) // 4096 * 4096
    ):
        raise ValueError("invalid one-turn app scope")
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
    return BoundPaidTrial(
        app=_read_verified(paths.app, size, reviewed["image_sha256"]),
        ota1=_read_verified(paths.ota1, SLOT_BYTES, ranges[0]["sha256"]),
        nvs=_read_verified(paths.nvs, NVS_BYTES, ranges[1]["sha256"]),
        board_reference=board,
        factory_table_sha256=table_hash,
        factory_otadata_sha256=otadata_hash,
    )


def run_bound_paid_trial(
    paths: PaidTrialPaths, perform: Callable[[TrialStep, BoundPaidTrial], bool]
) -> TrialResult:
    claim = paths.review_dir / "install-started.json"
    if claim.exists():
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
        )
        if not scopes.complete:
            return TrialResult(approval_rejected=True)
        reviewed = json.loads(document)
        if not isinstance(reviewed, dict):
            return TrialResult(approval_rejected=True)
        inputs = _bind_files(paths, reviewed, approved)
    except (OSError, KeyError, ValueError, TypeError):
        return TrialResult(approval_rejected=True)

    def step_for_review(step: TrialStep) -> bool:
        if step is TrialStep.CLAIM_ONCE:
            if (
                _read_bounded(approval_path, 64 * 1024) != approval_document
                or _read_bounded(manifest_path, 64 * 1024) != document
            ):
                return False
            with claim.open("x", encoding="ascii") as stream:
                json.dump({"review_sha256": review_sha}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            return True
        return perform(step, inputs)

    return run_paid_trial(scopes, step_for_review)
