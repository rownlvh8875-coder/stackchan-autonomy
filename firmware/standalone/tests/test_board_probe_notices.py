"""Review archives must carry project, IDF and FreeRTOS permission notices."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from collect_board_probe_notices import collect


def test_required_notices_and_component_inventory(tmp_path):
    idf = tmp_path / "idf"
    for name in [
        "LICENSE",
        "components/freertos/FreeRTOS-Kernel/LICENSE.md",
        "components/freertos/FreeRTOS-Kernel/include/freertos/FreeRTOS.h",
        "components/other/NOTICE.txt",
    ]:
        path = idf / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("permission: " + name)
    out = tmp_path / "notices"
    inventory = collect(idf, out)
    assert (out / "PROJECT-MIT-LICENSE.txt").is_file()
    assert (out / "ESP-IDF-LICENSE").read_text() == "permission: LICENSE"
    assert (out / "components/freertos/FreeRTOS-Kernel/LICENSE.md").is_file()
    assert (out / "components/freertos/FreeRTOS-Kernel/include/freertos/FreeRTOS.h").is_file()
    assert (out / "components/other/NOTICE.txt").is_file()
    assert len(inventory) >= 5 and all(len(item["sha256"]) == 64 for item in inventory)


def test_missing_required_notice_fails_before_publication(tmp_path):
    with pytest.raises(ValueError):
        collect(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
