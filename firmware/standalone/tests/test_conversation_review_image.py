"""The public operating review must contain the model and deny device activation."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_conversation_image as checker  # noqa: E402
from check_conversation_image import inspect_image, main, verify_sdkconfig  # noqa: E402
from test_board_probe_image import TABLE  # noqa: E402
from test_resource_bench_image import ELF_SHA, image  # noqa: E402
from test_resource_bench_image import pack as resource_pack  # noqa: E402

pinned_pack = resource_pack

PROJECT = b"k151_conversation_review"
REVIEW = b"W (%lu) %s: K151_CONVERSATION_REVIEW_NO_RELEASE\n\0"
ONE_TURN = b"K151_CONVERSATION_LOCAL_RELEASE_ONE_PAID_TURN\0"
DEVICE_OBSERVED = b"K151_CONVERSATION_LOCAL_RELEASE_ONE_PAID_TURN_DEVICE_OBSERVED\0"
CONTINUOUS = b"K151_CONVERSATION_LOCAL_RELEASE_CONTINUOUS\0"
REBOOT_TRIAL = b"K151_CONVERSATION_LOCAL_RELEASE_REBOOT_TRIAL\0"
STATUS = b"Say Hi StackChan\0Standby verified. Trial ended.\0"
ROUTE = b"/v1/realtime?model=gpt-realtime-2.1-mini\0"
PRIVATE_TABLE = "nvs,data,nvs,0x9000,0x4000,\n" + TABLE


def test_review_scope_is_bound_to_app_elf_and_model(pinned_pack):
    fixture = image(pinned_pack + REVIEW + STATUS + ROUTE, project=PROJECT)
    report = inspect_image(fixture, ELF_SHA, TABLE)
    assert report["install_authorized"] is False
    assert report["operating_admission"] is False
    assert report["physical_boot_inference_or_tls_validated"] is False
    assert report["private_board_policy_embedded"] is False
    assert report["model_in_readonly_app_segment"] is True
    assert report["write_bytes"] == len(fixture) and report["write_offset"] == 0x510000
    assert report["selected_partition"] == "ota_1"


@pytest.mark.parametrize(
    "payload",
    [
        STATUS + ROUTE,
        REVIEW + ROUTE,
        REVIEW + STATUS,
        REVIEW + STATUS + ROUTE + b"K151_CONVERSATION_LOCAL_RELEASE\0",
        REVIEW + STATUS + ROUTE + b"Error write Upgrade header",
    ],
)
def test_refuse_missing_paths_private_policy_and_unsafe_logging(pinned_pack, payload):
    with pytest.raises(ValueError):
        inspect_image(image(pinned_pack + payload, project=PROJECT), ELF_SHA, TABLE)


@pytest.mark.parametrize(
    ("marker", "basis"),
    [(ONE_TURN, "electrical_measurement"), (DEVICE_OBSERVED, "device_diagnostics")],
)
def test_private_review_requires_one_turn_marker_and_keeps_approval_unset(
    pinned_pack, marker, basis
):
    fixture = image(pinned_pack + marker + STATUS + ROUTE, project=PROJECT)
    report = inspect_image(fixture, ELF_SHA, PRIVATE_TABLE, local_one_turn=True)
    assert report["private_board_policy_embedded"] is True
    assert report["install_authorized"] is False and report["paid_api_called"] is False
    assert report["one_turn_output_basis"] == basis
    assert report["physical_output_or_stop_proven"] is False
    with pytest.raises(ValueError, match="NVS"):
        inspect_image(fixture, ELF_SHA, TABLE, local_one_turn=True)


@pytest.mark.parametrize(
    "markers",
    [
        REVIEW,
        CONTINUOUS,
        REBOOT_TRIAL,
        ONE_TURN + REBOOT_TRIAL,
        ONE_TURN + CONTINUOUS,
        ONE_TURN + REVIEW,
        ONE_TURN + DEVICE_OBSERVED,
    ],
)
def test_private_review_rejects_other_build_modes(pinned_pack, markers):
    fixture = image(pinned_pack + markers + STATUS + ROUTE, project=PROJECT)
    with pytest.raises(ValueError):
        inspect_image(fixture, ELF_SHA, PRIVATE_TABLE, local_one_turn=True)


@pytest.mark.parametrize("mode", ["--local-one-turn", "--local-reboot-trial"])
def test_local_review_refuses_ci_before_opening_any_artifact(monkeypatch, tmp_path, capsys, mode):
    monkeypatch.setenv("CI", "true")
    argv = [mode]
    for option in (
        "elf",
        "bin",
        "partition-csv",
        "sdkconfig",
        "out",
        "factory-a",
        "factory-b",
        "factory-ota1",
        "pretrial-nvs",
    ):
        argv.extend((f"--{option}", str(tmp_path / option)))
    for option in ("idf-head", "source-head", "factory-sha256"):
        argv.extend((f"--{option}", "fixture"))
    if mode == "--local-reboot-trial":
        argv.extend(("--idf-dir", str(tmp_path / "idf")))
    with pytest.raises(SystemExit) as error:
        main(argv)
    assert error.value.code == 2
    assert "requires local execution" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_review_requires_psram_serial_separation_and_one_ms_scheduler():
    config = "\n".join(
        (
            "CONFIG_SPIRAM=y",
            "CONFIG_SPIRAM_MODE_QUAD=y",
            "CONFIG_SPIRAM_SPEED_80M=y",
            "CONFIG_SPIRAM_USE_MALLOC=y",
            "CONFIG_FREERTOS_HZ=1000",
            "CONFIG_ESP_MAIN_TASK_AFFINITY_CPU0=y",
            "CONFIG_ESP_MAIN_TASK_STACK_SIZE=12288",
            "CONFIG_ESP_CONSOLE_UART_DEFAULT=y",
            "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y",
            "CONFIG_ESP_COREDUMP_ENABLE_TO_NONE=y",
        )
    )
    verify_sdkconfig(config)
    with pytest.raises(ValueError, match="CONFIG_SPIRAM_USE_MALLOC"):
        verify_sdkconfig(config.replace("CONFIG_SPIRAM_USE_MALLOC=y", ""))


REBOOT_STATUS = b"Reboot ready. Power off and on.\0Previous budget verified\0"


def test_reboot_review_binds_separate_cap_and_nvs_scope(pinned_pack):
    fixture = image(pinned_pack + REBOOT_TRIAL + STATUS + REBOOT_STATUS + ROUTE, project=PROJECT)
    report = inspect_image(fixture, ELF_SHA, PRIVATE_TABLE, local_reboot_trial=True)
    assert report["kind"] == "LOCAL_REBOOT_PAID_TRIAL_REVIEW"
    assert report["reboot_trial_paid_turns"] == {"before_reboot": 1, "after_reboot": 2}
    assert report["runtime_budget_write_scope"] == ["sc_gpt/budget", "sc_gpt/trial_ckpt"]
    assert report["install_authorized"] is False and report["paid_api_called"] is False
    with pytest.raises(ValueError, match="NVS"):
        inspect_image(fixture, ELF_SHA, TABLE, local_reboot_trial=True)


@pytest.mark.parametrize(
    "markers,status",
    [
        (REBOOT_TRIAL, STATUS),
        (CONTINUOUS, STATUS + REBOOT_STATUS),
        (ONE_TURN, STATUS + REBOOT_STATUS),
        (REBOOT_TRIAL + ONE_TURN, STATUS + REBOOT_STATUS),
        (REBOOT_TRIAL + DEVICE_OBSERVED, STATUS + REBOOT_STATUS),
        (REBOOT_TRIAL + REVIEW, STATUS + REBOOT_STATUS),
        (REBOOT_TRIAL + CONTINUOUS, STATUS + REBOOT_STATUS),
    ],
)
def test_combined_review_refuses_incompatible_images(pinned_pack, markers, status):
    fixture = image(pinned_pack + markers + status + ROUTE, project=PROJECT)
    with pytest.raises(ValueError):
        inspect_image(fixture, ELF_SHA, PRIVATE_TABLE, local_reboot_trial=True)


@pytest.mark.parametrize("changed_snapshot", [False, True])
def test_reboot_manifest_uses_verified_restore_snapshot(
    pinned_pack, monkeypatch, tmp_path, capsys, changed_snapshot
):
    monkeypatch.delenv("CI", raising=False)
    app = image(pinned_pack + REBOOT_TRIAL + STATUS + REBOOT_STATUS + ROUTE, project=PROJECT)
    (tmp_path / "bin").write_bytes(app)
    (tmp_path / "partition-csv").write_text(PRIVATE_TABLE, encoding="utf-8")
    (tmp_path / "sdkconfig").touch()
    monkeypatch.setattr(checker, "verify_sdkconfig", lambda _: None)
    monkeypatch.setattr(
        checker, "validate", lambda *_: {"elf": {"sha256": ELF_SHA}, "idf_commit": "fixture"}
    )
    monkeypatch.setattr(
        checker,
        "verify_trial_restore",
        lambda *_: {
            "restore_authorized": False,
            "restore_in_order": [{"partition": "ota_1"}, {"partition": "nvs", "sha256": "a" * 64}],
        },
    )

    def read_baseline(snapshot, idf, *, require_fresh_reboot_trial):
        assert snapshot == tmp_path / "pretrial-nvs" and idf == tmp_path / "idf-dir"
        assert require_fresh_reboot_trial is True
        return {
            "pretrial_nvs_sha256": ("b" if changed_snapshot else "a") * 64,
            "trial_budget_must_be_missing": False,
            "trial_budget_sha256": "c" * 64,
        }

    monkeypatch.setattr(checker, "inspect_pinned_snapshot", read_baseline)
    args = ["--local-reboot-trial"]
    for option in (
        "elf",
        "bin",
        "partition-csv",
        "sdkconfig",
        "out",
        "idf-dir",
        "factory-a",
        "factory-b",
        "factory-ota1",
        "pretrial-nvs",
    ):
        args.extend((f"--{option}", str(tmp_path / option)))
    args.extend(
        (
            "--idf-head",
            "fixture",
            "--source-head",
            "012345abcdef" + "0" * 28,
            "--factory-sha256",
            "fixture",
        )
    )
    status = main(args)
    output = tmp_path / "out"
    if changed_snapshot:
        assert status == 2 and not output.exists()
        assert capsys.readouterr().out.strip() == "LOCAL_REBOOT_PAID_TRIAL_REVIEW_REJECTED"
    else:
        assert status == 0
        report = json.loads(output.read_bytes())
        assert report["budget_baseline"]["trial_budget_sha256"] == "c" * 64
        assert report["fresh_reboot_state_verified"] is True
        assert report["runtime_owner_setup_write_scope"] == "sc_owner/owner_cfg_v2"
        assert report["install_authorized"] is False
        assert report["recovery"]["restore_authorized"] is False
