"""Fixed historical evidence must remain accurate, bounded and fail closed."""

import importlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

REPORT_NAME = "windows-home-soak-24h-passed.json"
SOURCE = (
    Path(__file__).resolve().parents[1]
    / "docs/validation/2026-11-15-windows-home-soak-24h-passed.json"
)


def test_summary_is_historical_pc_mock_wall_clock_evidence():
    module = importlib.import_module("stackchan_autonomy.soak_summary")
    assert module.load_soak_summary() == {
        "report_id": "windows-home-soak-24h-2026-11-15",
        "recorded_date": "2026-11-15",
        "recorded_date_basis": "report_received",
        "recorded_timezone": "Asia/Seoul",
        "historical": True,
        "test_scope": "pc_fake_mock",
        "time_mode": "wall_clock",
        "robot_hardware_tested": False,
        "memory_measurement": "python_tracemalloc_growth_not_process_rss",
        "passed": True,
        "wall_elapsed_s": 86400.047,
        "requested_duration_s": 86400.0,
        "cycles": 83157,
        "restarts": 332,
        "restoration_checks": 332,
        "python_traced_growth_bytes": 20697,
        "task_growth": 0,
        "remaining_tasks": 0,
        "cloud_requests": 0,
        "violations": [],
        "failure": None,
    }


def test_resource_matches_original_evidence_bytes():
    resource = files("stackchan_autonomy").joinpath("data", REPORT_NAME)
    assert resource.read_bytes() == SOURCE.read_bytes()


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "malformed",
        "oversized",
        "missing_field",
        "extra_secret",
        "passed_string",
        "cycles_boolean",
        "duration_short",
        "duration_nan",
        "virtual_time",
        "failure",
        "altered_cycles",
    ],
)
def test_unavailable_resource_never_becomes_pass_or_discloses_contents(
    corruption, monkeypatch, tmp_path, capsys, caplog
):
    module = importlib.import_module("stackchan_autonomy.soak_summary")
    data = json.loads(SOURCE.read_bytes())
    private = "private-report-content-no-echo"
    updates = {
        "extra_secret": {"secret": private},
        "passed_string": {"passed": "true"},
        "cycles_boolean": {"cycles": True},
        "duration_short": {"wall_elapsed_s": 600.0},
        "duration_nan": {"wall_elapsed_s": float("nan")},
        "virtual_time": {"virtual_elapsed_s": 86400.0},
        "failure": {"failure": {"message": private}},
        "altered_cycles": {"cycles": 1},
    }
    data.update(updates.get(corruption, {}))
    if corruption == "missing_field":
        del data["passed"]
    raw = json.dumps(data).encode()
    if corruption == "malformed":
        raw = ("{" + private).encode()
    if corruption == "oversized":
        raw = private.encode() + b" " * (16 * 1024 + 1)
    resource = tmp_path / "data" / REPORT_NAME
    resource.parent.mkdir()
    if corruption != "missing":
        resource.write_bytes(raw)
    monkeypatch.setattr(module, "files", lambda package: tmp_path)
    with pytest.raises(module.SoakSummaryUnavailable) as caught:
        module.load_soak_summary()
    assert str(caught.value) == "PC_SOAK_REPORT_UNAVAILABLE"
    observed = str(caught.value) + repr(caught.value) + str(capsys.readouterr()) + caplog.text
    assert private not in observed
    assert str(tmp_path) not in observed
