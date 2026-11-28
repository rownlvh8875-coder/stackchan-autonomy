"""Use synthetic NVS records with the pinned parser's fields. No device I/O."""

import hashlib
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from zlib import crc32

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_trial_budget_snapshot import inspect_snapshot  # noqa: E402

SNAPSHOT = b"\xff" * 0x4000


def ledger():
    record = b"BUD1\x01\x01" + struct.pack("<QQ", 1_700_000_000, 1_700_000_000)
    return record + struct.pack("<I", crc32(record))


def entry(ns, kind, name, data, *, chunk=255, children=(), data_crc=0):
    return SimpleNamespace(
        state="Written",
        key=name,
        data=data,
        children=children,
        metadata={
            "namespace": ns,
            "type": kind,
            "chunk_index": chunk,
            "span": len(children) + 1,
            "crc": {
                "original": 1,
                "computed": 1,
                "data_original": data_crc,
                "data_computed": data_crc,
            },
        },
    )


def inspect(entries, *, raw=SNAPSHOT, page_state="Active", **scope):
    page = SimpleNamespace(
        header={
            "status": page_state,
            "version": 2,
            "page_index": 0,
            "crc": {"original": 1, "computed": 1},
        },
        entries=entries,
        start_address=0,
    )
    return inspect_snapshot(raw, lambda *_: SimpleNamespace(pages=[page]), **scope)


def fixture(payload=None):
    payload = payload if payload is not None else ledger()
    namespace = entry(0, "uint8_t", "sc_gpt", {"value": 7})
    index = entry(
        7, "blob_index", "budget", {"size": len(payload), "chunk_count": 1, "chunk_start": 128}
    )
    chunk = entry(
        7,
        "blob_data",
        "budget",
        {"size": len(payload)},
        chunk=128,
        children=[SimpleNamespace(state="Written", raw=payload.ljust(32, b"\xff"))],
        data_crc=crc32(payload, 0xFFFFFFFF),
    )
    return [namespace, index, chunk]


def test_report_is_only_a_digest_and_never_equals_live_verification():
    rows = fixture()
    rows.append(entry(8, "uint8_t", "synthetic_private_setting", {"value": 19}))
    result = inspect(rows)
    assert result["trial_budget_must_be_missing"] is False
    assert result["trial_budget_sha256"] == hashlib.sha256(ledger()).hexdigest()
    assert result["pretrial_nvs_sha256"] == hashlib.sha256(SNAPSHOT).hexdigest()
    assert result["current_device_verified"] is False
    assert result["provisioning_authorized"] is False
    assert "synthetic_private_setting" not in repr(result)


def test_absent_record_is_reported_without_granting_provisioning():
    result = inspect(fixture()[:1])
    assert result["trial_budget_must_be_missing"] is True
    assert result["trial_budget_sha256"] is None
    assert result["provisioning_authorized"] is False


def test_indexed_budget_chunks_are_reassembled_in_index_order():
    rows = fixture()
    value = ledger()
    rows[1].data["chunk_count"] = 2
    rows.pop()
    for index, data in reversed(list(enumerate((value[:12], value[12:]), start=128))):
        rows.append(
            entry(
                7,
                "blob_data",
                "budget",
                {"size": len(data)},
                chunk=index,
                children=[SimpleNamespace(state="Written", raw=data.ljust(32, b"\xff"))],
                data_crc=crc32(data, 0xFFFFFFFF),
            )
        )
    assert inspect(rows)["trial_budget_sha256"] == hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize(
    "breakage", ["index", "chunk", "orphan", "bad_crc", "invalid_page", "partial"]
)
def test_unresolved_snapshot_never_looks_like_absent_budget(breakage):
    rows = fixture()
    raw = SNAPSHOT
    page = "Active"
    if breakage == "index":
        rows.append(rows[1])
    elif breakage == "chunk":
        rows.append(rows[2])
    elif breakage == "orphan":
        rows.pop(1)
    elif breakage == "bad_crc":
        rows[2].metadata["crc"]["data_computed"] = 0
    elif breakage == "invalid_page":
        page = "Erasing"
    else:
        raw = SNAPSHOT[:-1]
    with pytest.raises(ValueError):
        inspect(rows, raw=raw, page_state=page)


def test_bad_budget_wire_does_not_produce_a_digest():
    value = ledger()
    with pytest.raises(ValueError):
        inspect(fixture(value[:-1] + bytes([value[-1] ^ 1])))


@pytest.mark.parametrize(
    "namespace,key",
    [("sc_gpt", "trial_ckpt"), ("sc_owner", "owner_cfg_v2")],
)
def test_combined_review_refuses_preexisting_trial_state(namespace, key):
    rows = fixture()
    slot = 7 if namespace == "sc_gpt" else 8
    if slot == 8:
        rows.append(entry(0, "uint8_t", namespace, {"value": slot}))
    rows.append(entry(slot, "blob_index", key, {"size": 48}))
    assert inspect(rows)["trial_budget_must_be_missing"] is False
    with pytest.raises(ValueError, match="preexisting trial state"):
        inspect(rows, require_fresh_reboot_trial=True)
