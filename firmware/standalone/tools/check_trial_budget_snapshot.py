"""Prepare only the sc_gpt/budget baseline from a local pretrial NVS snapshot."""

import argparse
import hashlib
import json
import os
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zlib import crc32

from check_idf_build import EXPECTED_IDF_SHA

NVS_BYTES = 0x4000
PAGE_BYTES = 0x1000
VENDOR_PARSER = "components/nvs_flash/nvs_partition_tool/nvs_parser.py"


def _written_entries(snapshot: bytes, partition: Any) -> list:
    entries = []
    page_indices = set()
    for page in partition.pages:
        header = page.header
        if header["status"] == "Empty":
            start = page.start_address
            if snapshot[start : start + PAGE_BYTES] != b"\xff" * PAGE_BYTES:
                raise ValueError("unresolved empty NVS page")
            continue
        sequence = header["page_index"]
        if (
            header["status"] not in {"Active", "Full"}
            or header["version"] not in {1, 2}
            or header["crc"]["original"] != header["crc"]["computed"]
            or sequence in page_indices
        ):
            raise ValueError("unresolved NVS page")
        page_indices.add(sequence)
        for item in page.entries:
            if item.state not in {"Written", "Erased", "Empty"}:
                raise ValueError("unresolved NVS entry state")
            if item.state != "Written":
                continue
            crc = item.metadata["crc"]
            if (
                crc["original"] != crc["computed"]
                or item.metadata["span"] != 1 + len(item.children)
                or any(child.state != "Written" for child in item.children)
            ):
                raise ValueError("unresolved NVS entry")
            entries.append(item)
    return entries


def _chunk_payload(chunk: Any) -> bytes:
    size = chunk.data["size"]
    crc = chunk.metadata["crc"]
    payload = b"".join(child.raw for child in chunk.children)[:size]
    if (
        not 0 < size <= 818
        or len(payload) != size
        or crc["data_original"] != crc["data_computed"]
        or crc32(payload, 0xFFFFFFFF) != crc["data_original"]
    ):
        raise ValueError("unresolved budget blob data")
    return payload


def _budget_blob(items: list) -> bytes:
    if len(items) == 1 and items[0].metadata["type"] == "blob":
        return _chunk_payload(items[0])
    by_type = {kind: [] for kind in ("blob_index", "blob_data")}
    for item in items:
        kind = item.metadata["type"]
        if kind not in by_type:
            raise ValueError("unexpected budget item type")
        by_type[kind].append(item)
    if len(by_type["blob_index"]) != 1:
        raise ValueError("missing or duplicate budget blob index")
    index = by_type["blob_index"][0].data
    chunks = sorted(by_type["blob_data"], key=lambda item: item.metadata["chunk_index"])
    start = index["chunk_start"]
    expected = list(range(start, start + index["chunk_count"]))
    if start not in (0, 128) or [c.metadata["chunk_index"] for c in chunks] != expected:
        raise ValueError("missing, duplicate or unexpected budget chunk")
    payload = b"".join(_chunk_payload(chunk) for chunk in chunks)
    if len(payload) != index["size"]:
        raise ValueError("budget blob size mismatch")
    return payload


def _ledger_sha256(payload: bytes) -> str:
    # Match BudgetLedger::restore in standalone_core.hpp.
    if not 18 <= len(payload) <= 818 or payload[:5] != b"BUD1\x01":
        raise ValueError("invalid budget ledger header")
    count = payload[5]
    if len(payload) != 18 + count * 8 or crc32(payload[:-4]) != int.from_bytes(
        payload[-4:], "little"
    ):
        raise ValueError("invalid budget ledger size or checksum")
    last, *events = struct.unpack_from(f"<{count + 1}Q", payload, 6)
    if (not events and last != 0) or (
        events and (events[0] == 0 or events[-1] > last or events != sorted(events))
    ):
        raise ValueError("invalid budget ledger chronology")
    return hashlib.sha256(payload).hexdigest()


def inspect_snapshot(snapshot: bytes, parse: Callable[[str, bytearray], Any]) -> dict:
    if len(snapshot) != NVS_BYTES:
        raise ValueError("pretrial NVS snapshot size rejected")
    entries = _written_entries(snapshot, parse("pretrial", bytearray(snapshot)))
    namespaces = {}
    names = set()
    for item in entries:
        if item.metadata["namespace"] != 0:
            continue
        namespace = item.data["value"]
        if (
            item.metadata["type"] != "uint8_t"
            or not 1 <= namespace <= 254
            or item.key in names
            or namespace in namespaces
        ):
            raise ValueError("unresolved NVS namespace")
        names.add(item.key)
        namespaces[namespace] = item.key
    selected = [
        item
        for item in entries
        if item.key == "budget" and namespaces.get(item.metadata["namespace"]) == "sc_gpt"
    ]
    return {
        "kind": "LOCAL_NVS_BUDGET_BASELINE",
        "pretrial_nvs_sha256": hashlib.sha256(snapshot).hexdigest(),
        "trial_budget_must_be_missing": not selected,
        "trial_budget_sha256": _ledger_sha256(_budget_blob(selected)) if selected else None,
        "current_device_verified": False,
        "provisioning_authorized": False,
    }


def _pinned_parser(idf_dir: Path) -> Callable[[str, bytearray], Any]:
    # Load the pinned Git object directly, never a mutable working-tree copy.
    source = subprocess.run(
        ["git", "-C", str(idf_dir), "show", f"{EXPECTED_IDF_SHA}:{VENDOR_PARSER}"],
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    namespace: dict[str, Any] = {"__name__": "pinned_idf_nvs_parser"}
    exec(compile(source, VENDOR_PARSER, "exec"), namespace)
    return namespace["NVS_Partition"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("idf-dir", "snapshot", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if "CI" in os.environ:
        parser.error("the NVS budget baseline requires local execution")
    try:
        with args.snapshot.open("rb") as snapshot:
            report = inspect_snapshot(snapshot.read(NVS_BYTES + 1), _pinned_parser(args.idf_dir))
        with args.out.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("LOCAL_NVS_BUDGET_BASELINE_REJECTED")
        return 2
    print("LOCAL_NVS_BUDGET_BASELINE_WRITTEN_NO_AUTHORIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
