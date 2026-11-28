"""Offline variants of the published ESPHome factory/OTA pairs, with synthetic backups."""

import hashlib
import json
import struct

import pytest
from test_offline_factory_recovery import ENTRY, MD5_PREFIX
from test_offline_factory_recovery import synthetic as synthetic_factory
from test_resource_bench_image import image

synthetic = synthetic_factory

ALTERNATE = (
    (1, 0, 0x9000, 0x2000, b"otadata"),
    (1, 1, 0xB000, 0x1000, b"phy_init"),
    (0, 16, 0x10000, 0x7C0000, b"app0"),
    (0, 17, 0x7D0000, 0x7C0000, b"app1"),
    (1, 2, 0xF90000, 0x70000, b"nvs"),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def merged_image(app, *, layout=ALTERNATE):
    merged = bytearray(b"\xff" * 0x10000)
    merged[0] = 0xE9
    struct.pack_into("<H", merged, 12, 9)
    table = b"".join(
        ENTRY.pack(b"\xaa\x50", kind, subtype, offset, size, label, 0)
        for kind, subtype, offset, size, label in layout
    )
    table += MD5_PREFIX + hashlib.md5(table, usedforsecurity=False).digest()
    merged[0x8000 : 0x8000 + len(table)] = table
    return bytes(merged) + app


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    import check_esphome_transition as review

    def write(*, mismatch=False, layout=ALTERNATE, candidate_app=None):
        app = (
            candidate_app
            if candidate_app is not None
            else image(b"synthetic", project=b"stackchan-voice")
        )
        ota = image(b"alternate", project=b"stackchan-voice") if mismatch else app
        merged = merged_image(app, layout=layout)
        merged_path = tmp_path / "public-factory.bin"
        app_path = tmp_path / "public-ota.bin"
        merged_path.write_bytes(merged)
        app_path.write_bytes(ota)
        monkeypatch.setitem(
            review.RELEASES, "2026.11.0", ((len(merged), sha(merged)), (len(ota), sha(ota)))
        )
        return merged_path, app_path

    return write


def test_full_flash_rehearsal_reports_partition_and_interrupted_recovery(synthetic, candidate):
    from check_esphome_transition import rehearse

    factory_a, factory_b, digest = synthetic
    merged, ota = candidate()
    summary = rehearse(factory_a, factory_b, digest, "2026.11.0", merged, ota)
    assert summary["factory_backups_matched"] == 2
    assert summary["esp32s3_app_offset"] == 0x10000
    assert summary["partition_table_changes"] is True
    assert summary["alternate_nvs"]["offset"] == 0xF90000
    assert summary["candidate_write"]["erase_bytes"] == 0x11000
    assert summary["existing_ota1_nvs_restore_matches"] is False
    assert summary["initial_range_restore_after_alternate_nvs_write_matches"] is False
    assert summary["full_restore_range"] == {"offset": 0, "bytes": 0x1000000}
    assert summary["simulated_full_restore"] == {
        "partial_install": True,
        "alternate_nvs_write": True,
        "interrupted_full_restore": True,
    }
    assert summary["install_authorized"] is False and summary["physical_write_tested"] is False
    assert str(merged) not in json.dumps(summary) and digest not in json.dumps(summary)
    assert sha(factory_a.read_bytes()) == sha(factory_b.read_bytes()) == digest


@pytest.mark.parametrize("defect", ["mixed", "partition", "checksum", "digest"])
def test_incorrect_artifacts_are_rejected_without_disclosing_paths(
    synthetic, candidate, capsys, defect
):
    from check_esphome_transition import main

    factory_a, factory_b, digest = synthetic
    layout = ALTERNATE
    app = None
    if defect == "partition":
        layout = ALTERNATE[:-1] + ((1, 2, 0xF92000, 0x60000, b"nvs"),)
    if defect == "checksum":
        valid = image(b"synthetic", project=b"stackchan-voice")
        app = valid[:-1] + bytes([valid[-1] ^ 1])
    merged, ota = candidate(mismatch=defect == "mixed", layout=layout, candidate_app=app)
    if defect == "digest":
        ota.write_bytes(ota.read_bytes() + b"x")
    assert (
        main(
            [
                "--factory-a",
                str(factory_a),
                "--factory-b",
                str(factory_b),
                "--expected-sha256",
                digest,
                "--release",
                "2026.11.0",
                "--esphome-factory",
                str(merged),
                "--esphome-ota",
                str(ota),
            ]
        )
        == 2
    )
    assert capsys.readouterr().out.strip() == "ESPHOME_TRANSITION_REJECTED"
