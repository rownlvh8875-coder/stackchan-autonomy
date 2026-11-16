"""A bounded summary of one immutable, historical PC Fake/Mock test report."""

import hashlib
import json
from importlib.resources import files

# This digest identifies the original report, including its CRLF terminator.
# Verifying exact bytes validates the known fields without trusting arbitrary JSON.
_REPORT_SHA256 = "8ddbad0964b2249ed4d2b474b90836585f547b6e53d980c6d99f60eccc1cb728"
_REPORT_LIMIT = 16 * 1024


class SoakSummaryUnavailable(Exception):
    def __init__(self):
        super().__init__("PC_SOAK_REPORT_UNAVAILABLE")


def load_soak_summary() -> dict[str, object]:
    """Read only the bundled evidence; never accept a caller's path or raw text."""
    try:
        resource = files("stackchan_autonomy").joinpath("data", "windows-home-soak-24h-passed.json")
        with resource.open("rb") as stream:
            raw = stream.read(_REPORT_LIMIT + 1)
        if len(raw) > _REPORT_LIMIT or hashlib.sha256(raw).hexdigest() != _REPORT_SHA256:
            raise ValueError
        report = json.loads(raw)
        return {
            "report_id": "windows-home-soak-24h-2026-11-15",
            "recorded_date": "2026-11-15",
            "recorded_date_basis": "report_received",
            "recorded_timezone": "Asia/Seoul",
            "historical": True,
            "test_scope": "pc_fake_mock",
            "time_mode": "wall_clock",
            "robot_hardware_tested": False,
            "memory_measurement": "python_tracemalloc_growth_not_process_rss",
            "passed": report["passed"],
            "wall_elapsed_s": round(report["wall_elapsed_s"], 3),
            "requested_duration_s": report["requested_duration_s"],
            "cycles": report["cycles"],
            "restarts": report["restarts"],
            "restoration_checks": report["restoration_checks"],
            "python_traced_growth_bytes": report["python_traced_growth_bytes"],
            "task_growth": report["task_growth"],
            "remaining_tasks": report["remaining_tasks"],
            "cloud_requests": report["cloud_requests"],
            "violations": report["violations"],
            "failure": report["failure"],
        }
    except (OSError, ValueError, KeyError, TypeError):
        raise SoakSummaryUnavailable() from None
