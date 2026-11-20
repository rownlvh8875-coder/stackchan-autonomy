"""Safety regression: HOLD firmware must not activate unsafe K151 audio output."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_k151_physical_output_remains_hard_disabled():
    policy = (ROOT / "core/k151_output_evidence.hpp").read_text(encoding="utf-8")
    codec = (ROOT / "esp_app/main/k151_codec_port.cpp").read_text(encoding="utf-8")
    hold = (ROOT / "esp_app/main/app_main.cpp").read_text(encoding="utf-8")
    assert "kK151PhysicalOutputEnabledInHoldImage = false" in policy
    assert "kK151SafeDmaDrainDriverAvailable = false" in policy
    assert "if (!kK151PhysicalOutputEnabledInHoldImage ||" in codec
    assert "!kK151SafeDmaDrainDriverAvailable) return false;" in codec
    # A successful codec write alone does not satisfy physical-drain evidence.
    assert "bool K151CodecPort::drain_output_before_mute()" in codec
    assert (
        "return false;"
        in codec.split("bool K151CodecPort::drain_output_before_mute()", 1)[1].split(
            "bool K151CodecPort::quiet()", 1
        )[0]
    )
    assert "K151CodecPort audio" not in hold
    assert "for (;;) vTaskDelay(pdMS_TO_TICKS(1000));" in hold
