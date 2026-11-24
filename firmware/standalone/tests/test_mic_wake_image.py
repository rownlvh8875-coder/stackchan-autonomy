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


def test_question_trial_requires_separate_project_and_scope(model_fixture):
    from check_mic_wake_image import inspect_image

    app = image(model_fixture, project=b"k151_mic_question_trial")
    manifest = inspect_image(app, ELF_SHA, SLOT_CSV, question=True)
    assert manifest["kind"] == "RECEIVE_ONLY_MIC_QUESTION_TRIAL_NOT_OPERATIONAL"
    assert manifest["question_capture_deadline_ms"] == 8000
    assert manifest["question_initial_quiet_ms"] == 500
    assert manifest["combined_start_window_ms"] == 10000
    assert manifest["usb_exports_pcm"] is False
    assert manifest["install_authorized"] is False
    with pytest.raises(ValueError):
        inspect_image(app, ELF_SHA, SLOT_CSV)
    with pytest.raises(ValueError):
        inspect_image(image(model_fixture, project=PROJECT), ELF_SHA, SLOT_CSV, question=True)


def test_wake_only_control_has_distinct_identity_and_short_observation(model_fixture):
    from check_mic_wake_image import inspect_image

    app = image(model_fixture, project=b"k151_wake_only_control")
    manifest = inspect_image(app, ELF_SHA, SLOT_CSV, wake_only_control=True)
    assert manifest["kind"] == "RECEIVE_ONLY_WAKE_ONLY_CONTROL_NOT_OPERATIONAL"
    assert manifest["observation_frames_20ms"] == 75
    assert manifest["observation_pcm_ms"] == 1500
    assert manifest["combined_start_window_ms"] == 10000
    assert manifest["install_authorized"] is False
    with pytest.raises(ValueError):
        inspect_image(app, ELF_SHA, SLOT_CSV, question=True)
    with pytest.raises(ValueError):
        inspect_image(
            image(model_fixture, project=PROJECT), ELF_SHA, SLOT_CSV, wake_only_control=True
        )


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


def test_question_only_image_has_own_identity_and_no_model(model_fixture):
    from check_mic_wake_image import inspect_image

    project = b"k151_question_only"
    markers = b"QUESTION_ONLY_NOW\0MIC_QUESTION_ONLY_TRIAL_V1\0"
    app = image(markers, project=project)
    manifest = inspect_image(app, ELF_SHA, SLOT_CSV, question_only=True)
    assert manifest["kind"] == "RECEIVE_ONLY_QUESTION_ONLY_NOT_OPERATIONAL"
    assert manifest["wake_model_bundled"] is False
    assert manifest["question_capture_deadline_ms"] == 8000
    assert manifest["combined_start_window_ms"] == 10000
    assert manifest["install_authorized"] is False
    for unexpected in (model_fixture, b"LISTEN_NOW\0", b"MIC_WAKE_TRIAL_V4\0"):
        with pytest.raises(ValueError):
            inspect_image(
                image(markers + unexpected, project=project), ELF_SHA, SLOT_CSV, question_only=True
            )
    with pytest.raises(ValueError):
        inspect_image(image(model_fixture, project=PROJECT), ELF_SHA, SLOT_CSV, question_only=True)


def test_silent_tx_image_is_distinct_and_has_no_voice_trial(model_fixture):
    from check_mic_wake_image import inspect_image

    project = b"k151_silent_tx_probe"
    markers = b"WAIT_SILENT_TX_LOCAL_START\0K151_SILENT_TX_V1\0"
    manifest = inspect_image(image(markers, project=project), ELF_SHA, SLOT_CSV, silent_tx=True)
    assert manifest["kind"] == "GPIO_ISOLATED_SILENT_TX_NOT_OPERATIONAL"
    assert manifest["routes_audio_pins"] is False
    assert manifest["tx_descriptor_count"] == 2
    assert manifest["amplifier_or_fifo_drain_verified"] is False
    assert manifest["install_authorized"] is False
    for unexpected in (model_fixture, b"LISTEN_NOW\0", b"QUESTION_ONLY_NOW\0"):
        with pytest.raises(ValueError):
            inspect_image(
                image(markers + unexpected, project=project), ELF_SHA, SLOT_CSV, silent_tx=True
            )
    with pytest.raises(ValueError):
        inspect_image(
            image(markers, project=b"k151_question_only"), ELF_SHA, SLOT_CSV, silent_tx=True
        )


@pytest.mark.parametrize("protocol", ["K151_SPEAKER_V1", "K151_SPEAKER_V2", "K151_SPEAKER_V3"])
def test_speaker_probe_image_has_separate_identity_and_scope(model_fixture, protocol):
    from check_mic_wake_image import inspect_image

    challenge = {
        "K151_SPEAKER_V1": b"WAIT_SPEAKER_LOCAL_START\0",
        "K151_SPEAKER_V2": b'WAIT_SPEAKER_STARTUP_LOCAL_START\0"startup_stage"\0',
        "K151_SPEAKER_V3": (
            b'WAIT_SPEAKER_CLOCK_LOCAL_START\0"startup_stage"\0'
            b'"clock_wait_exit"\0"clock_wait_last"\0'
        ),
    }[protocol]
    markers = b"K151_SPEAKER_PROBE_NOT_OPERATIONAL\0" + challenge + protocol.encode() + b"\0"
    project = b"k151_speaker_probe"
    manifest = inspect_image(image(markers, project=project), ELF_SHA, SLOT_CSV, speaker=True)
    assert manifest["kind"] == "SYNTHETIC_SPEAKER_PROBE_NOT_OPERATIONAL"
    assert manifest["microphone_enabled"] is False
    assert manifest["cloud_enabled"] is False
    assert manifest["tone_samples"] == 6000
    assert manifest["tone_peak_pcm16"] == 4096
    assert manifest["install_authorized"] is False
    assert manifest["expected_protocol"] == protocol
    for unexpected in (model_fixture, b"LISTEN_NOW\0", b"QUESTION_ONLY_NOW\0", b"api.openai.com\0"):
        with pytest.raises(ValueError):
            inspect_image(
                image(markers + unexpected, project=project), ELF_SHA, SLOT_CSV, speaker=True
            )
    with pytest.raises(ValueError):
        inspect_image(
            image(markers, project=b"k151_silent_tx_probe"), ELF_SHA, SLOT_CSV, speaker=True
        )
