"""Exercise the approved one-turn operator sequence without opening any ports."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import paid_trial_operator as operator_tool  # noqa: E402
from paid_trial_sequence import TrialStep  # noqa: E402
from test_paid_trial_binding import review as review_fixture  # noqa: E402
from test_paid_trial_rom import Chip, Tool  # noqa: E402

review = review_fixture


class SimulatedOperator:
    def __init__(self, *, unplug_at=1, reconnect_at=4, answer="y", pairing="complete"):
        self.seconds = 0.0
        self.unplug_at = unplug_at
        self.reconnect_at = reconnect_at
        self.answer = answer
        self.pairing = pairing
        self.events = []

    def pair(self):
        self.events.append(("pair", self.seconds))
        if self.pairing == "timeout":
            raise subprocess.TimeoutExpired("mock child", 1)
        return self.pairing == "complete"

    def present(self):
        return self.seconds < self.unplug_at or self.seconds >= self.reconnect_at

    def key(self):
        if self.seconds >= 2:
            return self.answer
        return None

    def say(self, message):
        self.events.append(("prompt", message, self.seconds))

    def advance(self, seconds):
        self.seconds += seconds

    def run(self):
        return operator_tool.exercise_one_turn(
            self.pair, self.present, self.key, self.say, lambda: self.seconds, self.advance
        )

    def prompt(self, fragment):
        return next(event for event in self.events if event[0] == "prompt" and fragment in event[1])


def test_one_turn_requires_disconnect_then_owner_observation_then_reconnect():
    operator = SimulatedOperator()
    assert operator.run() is True
    assert operator.prompt("분리")[2] == 0
    assert operator.prompt("Hi StackChan")[2] >= operator.unplug_at
    assert operator.prompt("다시 연결")[2] >= 2
    assert operator.seconds >= operator.reconnect_at
    assert len([event for event in operator.events if event[0] == "pair"]) == 1
    assert not any(event[0] == "prompt" and "머리" in event[1] for event in operator.events)


@pytest.mark.parametrize(
    "settings",
    [
        {"unplug_at": float("inf")},
        {"reconnect_at": 1.5},
        {"answer": "n"},
        {"answer": None, "reconnect_at": float("inf")},
        {"reconnect_at": float("inf")},
        {"pairing": "timeout"},
        {"pairing": "denied"},
    ],
)
def test_missing_observation_or_attachment_cannot_report_a_successful_turn(settings):
    operator = SimulatedOperator(**settings)
    assert operator.run() is False
    assert operator.prompt("다시 연결")
    if "unplug_at" in settings or "pairing" in settings:
        assert not any(
            "Hi StackChan" in event[1] for event in operator.events if event[0] == "prompt"
        )
    assert operator.seconds <= 215


@pytest.mark.parametrize("replacement", [False, True])
def test_operator_bridge_waits_for_original_usb_identity_and_restores_reviewed_ranges(
    review, monkeypatch, replacement
):
    paths, _, _ = review
    device = Tool(paths)
    operator = SimulatedOperator()
    original = SimpleNamespace(vid=0x303A, pid=0x1001, device="mock-port", serial_number="original")
    other = SimpleNamespace(vid=0x303A, pid=0x1001, device="mock-port", serial_number="other")

    def ports():
        if not device.events:
            return [original]
        if ("trial", 1) not in device.events and operator.seconds < 1:
            return []  # Temporary USB removal immediately after the app boot reset.
        if ("trial", 1) not in device.events or operator.seconds < operator.unplug_at:
            return [original]
        if operator.seconds >= operator.reconnect_at:
            return [other if replacement else original]
        return []

    def run_pairing(arguments, *, timeout, check):
        assert device.events[-1] == ("close", 1)
        assert operator.seconds >= 1
        assert Path(arguments[1]).name == "scps_usb_cli.py"
        assert arguments[2:] == ["--port", "mock-port", "--interactive"]
        assert 0 < timeout <= 145 and check is False
        operator.unplug_at, operator.reconnect_at = 2, 5
        device.events.append(("trial", 1))
        device.flash[0x9000] = b"trial changed the NVS"
        return SimpleNamespace(returncode=0)

    tty = SimpleNamespace(isatty=lambda: True)
    console = SimpleNamespace(platform="win32", stdin=tty, stdout=tty, executable=sys.executable)
    clock = SimpleNamespace(monotonic=lambda: operator.seconds, sleep=operator.advance)
    keyboard = SimpleNamespace(kbhit=lambda: operator.seconds >= 3, getwch=lambda: "y")
    monkeypatch.setattr(operator_tool, "sys", console)
    monkeypatch.setattr(operator_tool, "time", clock)
    monkeypatch.setattr(operator_tool.subprocess, "run", run_pairing)
    monkeypatch.setattr(list_ports, "comports", ports)
    monkeypatch.setitem(sys.modules, "msvcrt", keyboard)
    monkeypatch.setitem(sys.modules, "scps_reference", SimpleNamespace(PcSession=object))
    monkeypatch.setattr("paid_trial_rom._load_esptool", lambda: (device.detect, Chip, device))

    result = operator_tool.run_operator_paid_trial(paths, "mock-port", lambda name: True)
    assert ("trial", 1) in device.events
    if replacement:
        assert result.recovery_failure is TrialStep.REBIND_FOR_RESTORE
        assert not result.factory_boot_requested
        assert device.connections == 1
        assert device.flash[0x9000] != paths.nvs.read_bytes()
    else:
        assert result.trial_failure is None and result.factory_boot_requested
        assert device.flash[0x9000] == paths.nvs.read_bytes()
