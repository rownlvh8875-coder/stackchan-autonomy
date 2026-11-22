"""The receive-only review package must bind its own app and embedded model."""

import hashlib

import pytest
from test_resource_bench_image import ELF_SHA, bench, image

SLOT_CSV = "ota_1,app,ota_1,0x510000,0x4f0000,\n"
PROJECT = b"k151_mic_wake_trial"


@pytest.fixture
def model_fixture(monkeypatch):
    model = b"test-trial-model"
    monkeypatch.setattr(bench, "PACK_PREFIX", model)
    monkeypatch.setattr(bench, "PACK_BYTES", len(model))
    monkeypatch.setattr(bench, "PACK_SHA256", hashlib.sha256(model).hexdigest())
    return model


def test_receive_only_scope(model_fixture):
    from check_mic_wake_image import inspect_image

    app = image(model_fixture, project=PROJECT)
    manifest = inspect_image(app, ELF_SHA, SLOT_CSV)
    assert manifest["write_offset"] == 0x510000 and manifest["write_bytes"] == len(app)
    assert manifest["selected_partition"] == "ota_1"
    assert manifest["model_in_readonly_app_segment"] is True
    assert manifest["capture_deadline_ms"] == 5000
    assert manifest["usb_exports_pcm"] is False
    assert manifest["install_authorized"] is False


@pytest.mark.parametrize("failure", ["other_project", "other_slot", "dup_pack", "ram_pack"])
def test_deny_other_app_or_invalid_pack(model_fixture, failure):
    from check_mic_wake_image import inspect_image

    table = SLOT_CSV
    app = image(model_fixture, project=PROJECT)
    if failure == "other_project":
        app = image(model_fixture)
    elif failure == "other_slot":
        table = table.replace("0x510000", "0x20000")
    elif failure == "dup_pack":
        app = image(model_fixture * 2, project=PROJECT)
    elif failure == "ram_pack":
        app = image(model_fixture, address=0x3FC90000, project=PROJECT)
    with pytest.raises(ValueError):
        inspect_image(app, ELF_SHA, table)
