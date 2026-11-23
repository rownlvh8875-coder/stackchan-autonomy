"""The display-only diagnostic must bind the reviewed OTA range and image."""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "tools"))
from check_board_probe import main, verify_panel_symbols  # noqa: E402
from test_board_probe_image import TABLE  # noqa: E402
from test_resource_bench_image import ELF_SHA, image  # noqa: E402


@pytest.mark.parametrize("symbol", ["i2s_new_channel", "esp_codec_dev_open", "nvs_flash_init"])
def test_panel_rejects_linked_io_even_if_transitive(symbol):
    with pytest.raises(ValueError, match="unexpected operational symbol"):
        verify_panel_symbols(f"40380000 T app_main\n40380020 T {symbol}\n")


def test_panel_image_applies_only_to_reviewed_slot(tmp_path, monkeypatch):
    app = tmp_path / "app.bin"
    app.write_bytes(image(b"panel-only", project=b"k151_panel_probe"))
    elf = tmp_path / "app.elf"
    elf.write_bytes(b"mock ELF")
    partitions = tmp_path / "table.csv"
    partitions.write_text(TABLE)
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        "check_board_probe.validate",
        lambda *_: {"elf": {"sha256": ELF_SHA}, "idf_commit": "fixture-idf"},
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        "check_board_probe.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="40380000 T app_main\n"),
    )
    from esp_app_image import inspect_envelope

    fields, _ = inspect_envelope(app.read_bytes(), ELF_SHA, b"k151_panel_probe")
    source = fields["app_version"] + ("0" * (40 - len(fields["app_version"])))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_board_probe.py",
            "--panel",
            "--nm",
            "fixture-nm",
            "--elf",
            str(elf),
            "--bin",
            str(app),
            "--idf-head",
            "fixture-idf",
            "--source-head",
            source,
            "--write-offset",
            "0x510000",
            "--partition-csv",
            str(partitions),
            "--out",
            str(manifest),
        ],
    )
    assert main() == 0
    report = json.loads(manifest.read_text())
    assert report["kind"] == "PANEL_HEAD_STOP_PROBE_NOT_OPERATIONAL"
    assert report["device_configuration_writes"] is True
    assert report["install_authorized"] is False
    assert report["operating_admission"] is False
    assert report["physical_panel_head_stop_verified"] is False
    assert report["no_operational_symbols_verified"] is True
    assert report["write_bytes"] == app.stat().st_size
    assert report["selected_partition"] == "ota_1"


def test_panel_flag_rejects_another_project():
    from check_board_probe import inspect_image

    with pytest.raises(ValueError, match="unexpected diagnostic app project"):
        inspect_image(
            image(b"other", project=b"k151_board_probe"),
            ELF_SHA,
            write_offset=0x510000,
            partition_csv=TABLE,
            panel=True,
        )


def test_stop_only_build_binds_a_separate_project_and_excludes_head_sensor():
    from check_board_probe import inspect_image

    stop_protocol = b"K151_PANEL_SCREEN_STOP_PROBE_NOT_OPERATIONAL\x00"
    report = inspect_image(
        image(stop_protocol, project=b"k151_screen_stop_probe"),
        ELF_SHA,
        write_offset=0x510000,
        partition_csv=TABLE,
        screen_stop_only=True,
    )
    assert report["kind"] == "PANEL_SCREEN_STOP_PROBE_NOT_OPERATIONAL"
    assert report["head_sensor_in_trial"] is False
    assert report["maximum_trial_ms"] == 10000
    assert report["install_authorized"] is report["operating_admission"] is False
    with pytest.raises(ValueError, match="protocol marker absent"):
        inspect_image(
            image(b"another protocol", project=b"k151_screen_stop_probe"),
            ELF_SHA,
            write_offset=0x510000,
            partition_csv=TABLE,
            screen_stop_only=True,
        )
    with pytest.raises(ValueError, match="unexpected head sensor symbol"):
        verify_panel_symbols(
            "40380000 T app_main\n40380004 T _ZN17K151HeadTouchOwner13poll_once\n",
            screen_stop_only=True,
        )
