"""The public operating review must contain the model and deny device activation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_conversation_image import inspect_image, verify_sdkconfig  # noqa: E402
from test_board_probe_image import TABLE  # noqa: E402
from test_resource_bench_image import ELF_SHA, image  # noqa: E402
from test_resource_bench_image import pack as resource_pack  # noqa: E402

pinned_pack = resource_pack

PROJECT = b"k151_conversation_review"
REVIEW = b"K151_CONVERSATION_REVIEW_NO_RELEASE\0"
STATUS = b"Say Hi StackChan\0Standby verified. Trial ended.\0"
ROUTE = b"/v1/realtime?model=gpt-realtime-2.1-mini\0"


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
