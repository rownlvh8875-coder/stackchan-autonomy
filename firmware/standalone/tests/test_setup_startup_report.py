"""Check the setup-only report without opening a serial device."""

import sys
from io import BytesIO
from itertools import count
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from collect_setup_startup import read_report  # noqa: E402


class Port(BytesIO):
    def read_until(self, expected, size):
        assert expected == b"\n"
        return self.readline(min(size, 13))

    def write(self, _data):
        pytest.fail("collector must be receive-only")


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        (b"4 0 1\n", {"boot": "psram", "setup": "idle", "cleanup": True}),
        (b"8 7 1\n", {"boot": "ready", "setup": "presence_frame", "cleanup": True}),
        (b"8 8 0\n", {"boot": "ready", "setup": "head", "cleanup": False}),
        (b"8 10 1\n", {"boot": "ready", "setup": "ready", "cleanup": True}),
        (b"8 0 1\n", None),
        (b"4 7 1\n", None),
        (b"8 11 1\n", None),
        (b"4 0 0\n", None),
        (b"8 10 2\n", None),
        (b"8 10 1 appended\n", None),
    ],
)
def test_only_bounded_stage_records_are_returned(wire, expected):
    port = Port(b"unrelated boot text\nK151_SETUP_STARTUP_PROBE_V1 " + wire)
    assert read_report(port, clock=count().__next__) == expected


def test_timeout_and_overlong_noise_cannot_be_mistaken_for_a_report():
    prefix = b"K151_SETUP_STARTUP_PROBE_V1 "
    port = Port(b"x" * 101 + prefix + b"8 10 1\n")
    assert read_report(port, clock=count().__next__) is None
