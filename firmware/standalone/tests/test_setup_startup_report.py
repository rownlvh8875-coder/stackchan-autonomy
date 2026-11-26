"""Check the setup-only report without opening a serial device."""

import json
import sys
from io import BytesIO
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import collect_setup_startup as collector  # noqa: E402
import scps_usb_wire as wire  # noqa: E402
from collect_setup_startup import read_report  # noqa: E402


class Port(BytesIO):
    def read(self, size):
        return super().read(min(size, 13))

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


@pytest.mark.parametrize(
    ("prefix", "verdict"),
    [
        (b"boot" * 512, "probe_received"),
        (b"boot" * 512 + b"x", "startup_prefix_limit"),
        (wire.MAGIC + b"\x00\x01\x56\x00", "invalid_header"),
    ],
)
def test_scps_probe_separates_production_verdict_from_passive_observation(
    monkeypatch, prefix, verdict
):
    frame = wire.encode(wire.Frame(wire.Op.DEVICE_HELLO, bytes(86)))
    footer = b"\nK151_SETUP_STARTUP_PROBE_V2 8 10 1 2\n"
    ticks = count()

    def clock():
        return next(ticks) / 1000

    monkeypatch.setattr(wire, "time", SimpleNamespace(monotonic=clock))
    report = collector.read_scps_report(Port(prefix + frame + footer), clock=clock)
    assert report == {
        "first_response": verdict,
        "probe_offset": len(prefix),
        "startup": {"boot": "ready", "setup": "ready", "cleanup": True, "tx": "drained"},
    }


@pytest.mark.parametrize(
    ("data", "verdict", "offset", "startup"),
    [
        (b"", "response_timeout", None, None),
        (b"x" * 9000, "startup_prefix_limit", None, None),
        (
            b"\nK151_SETUP_STARTUP_PROBE_V2 8 8 1 0\n",
            "startup_without_frame",
            None,
            {"boot": "ready", "setup": "head", "cleanup": True, "tx": "skipped"},
        ),
        (
            wire.encode(wire.Frame(wire.Op.DEVICE_HELLO, b"\x01" * 86)),
            "unexpected_probe_payload",
            None,
            None,
        ),
    ],
)
def test_scps_probe_requires_exact_fixture_and_bounds_observation(
    monkeypatch, data, verdict, offset, startup
):
    ticks = count()

    def clock():
        return next(ticks) / 1000

    monkeypatch.setattr(wire, "time", SimpleNamespace(monotonic=clock))
    port = Port(data)
    assert collector.read_scps_report(port, clock=clock) == {
        "first_response": verdict,
        "probe_offset": offset,
        "startup": startup,
    }
    assert port.tell() <= 8192


@pytest.mark.parametrize(("prefix_length", "exit_code"), [(2048, 0), (2049, 1)])
def test_scps_cli_fails_closed_with_only_metadata(monkeypatch, capsys, prefix_length, exit_code):
    prefix = b"private-serial-text".ljust(prefix_length, b"x")
    frame = wire.encode(wire.Frame(wire.Op.DEVICE_HELLO, bytes(86)))
    footer = b"\nK151_SETUP_STARTUP_PROBE_V2 8 10 1 2\n"

    class ProbePort(Port):
        def __enter__(self):
            assert self.port == "COM3" and not self.dtr and not self.rts
            return super().__enter__()

    port = ProbePort(prefix + frame + footer)
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=lambda **_: port))
    assert collector.main(["--port", "COM3", "--scps-probe"]) == exit_code
    output = capsys.readouterr().out
    assert "private-serial-text" not in output
    assert json.loads(output)["probe_offset"] == prefix_length
