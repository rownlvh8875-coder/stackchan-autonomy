"""Board readback image review is independent of the silent model bench."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_board_probe as board
from test_resource_bench_image import ELF_SHA, image

TABLE = "ota_0,app,ota_0,0x20000,0x4f0000,\nota_1,app,ota_1,0x510000,0x4f0000,\n"


def inspect(app, elf=ELF_SHA, offset=0x510000, table=TABLE):
    return board.inspect_image(app, elf, write_offset=offset, partition_csv=table)


def test_board_envelope():
    app = image(b"board-only", project=b"k151_board_probe")
    result = inspect(app)
    assert result["kind"] == "READONLY_BOARD_PROBE_NOT_OPERATIONAL"
    assert result["write_offset"] == 0x510000
    assert result["image_sha256"] == hashlib.sha256(app).hexdigest()
    assert result["write_bytes"] == len(app)
    assert result["install_authorized"] is False
    assert result["operating_admission"] is False
    assert result["device_configuration_writes"] is False
    assert result["gpio_mux_changes_after_start"] is True


def test_power_review_rejects_board_image_and_requires_power_specific_markers():
    project = b"k151_power_readback"
    markers = b"K151_POWER_READBACK_NOT_OPERATIONAL\0WAIT_POWER_LOCAL_START\0K151_POWER_READBACK_V1"
    manifest = board.inspect_image(
        image(markers, project=project),
        ELF_SHA,
        write_offset=0x510000,
        partition_csv=TABLE,
        power_readback=True,
    )
    assert manifest["kind"] == "READONLY_POWER_READBACK_NOT_OPERATIONAL"
    assert manifest["expected_protocol"] == "K151_POWER_READBACK_V1"
    assert manifest["device_configuration_writes"] is False
    assert manifest["power_mute_or_audio_readiness_proven"] is False
    assert manifest["install_authorized"] is False
    for wrong in (image(markers, project=b"k151_board_probe"), image(b"missing", project=project)):
        with pytest.raises(ValueError):
            board.inspect_image(
                wrong,
                ELF_SHA,
                write_offset=0x510000,
                partition_csv=TABLE,
                power_readback=True,
            )


def test_power_elf_rejects_i2c_configuration_writer():
    listing = "0001 T app_main\n0002 T i2c_master_transmit_receive\n"
    board.verify_panel_symbols(listing, power_readback=True)
    with pytest.raises(ValueError, match="configuration write"):
        board.verify_panel_symbols(listing + "0003 T i2c_master_transmit\n", power_readback=True)


@pytest.mark.parametrize("kind", ["bench", "elf", "chip", "revision", "corrupt", "oversized"])
def test_board_rejects_unrelated_or_invalid(kind):
    app = image(b"board-only", project=b"k151_board_probe")
    elf = ELF_SHA
    if kind == "bench":
        app = image(b"bench-model")
    elif kind == "elf":
        elf = "ff" * 32
    elif kind == "chip":
        app = image(b"board-only", project=b"k151_board_probe", chip=0)
    elif kind == "revision":
        app = image(b"board-only", project=b"k151_board_probe", minimum=3)
    elif kind == "corrupt":
        app = app[:-1] + bytes([app[-1] ^ 1])
    elif kind == "oversized":
        app = image(bytes(5_177_344), project=b"k151_board_probe")
    with pytest.raises(ValueError):
        inspect(app, elf)


@pytest.mark.parametrize(
    "kind", ["requested", "offset", "size", "type", "subtype", "overlap", "flags", "empty"]
)
def test_actual_build_partition_and_selected_write_must_match(kind):
    table = TABLE
    offset = 0x510000
    if kind == "requested":
        offset = 0x20000
    elif kind == "offset":
        table = table.replace("0x510000", "0x520000")
    elif kind == "size":
        table = table.replace("0x4f0000", "0x500000")
    elif kind == "type":
        table = table.replace("ota_1,app,", "ota_1,data,")
    elif kind == "subtype":
        table = table.replace("app,ota_1,", "app,ota_0,")
    elif kind == "overlap":
        table += "other,data,0x80,0x520000,4096,\n"
    elif kind == "flags":
        table = table.replace("0x4f0000,\n", "0x4f0000,encrypted\n")
    elif kind == "empty":
        table = ""
    with pytest.raises(ValueError):
        inspect(image(b"board-only", project=b"k151_board_probe"), offset=offset, table=table)
