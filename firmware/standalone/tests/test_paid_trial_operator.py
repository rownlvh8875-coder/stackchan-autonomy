"""Exercise the approved one-turn operator sequence without opening any ports."""

import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import paid_trial_operator as operator_tool  # noqa: E402
from paid_trial_sequence import TrialStep  # noqa: E402
from test_paid_trial_binding import review as review_fixture  # noqa: E402
from test_paid_trial_rom import Chip, Tool  # noqa: E402

review = review_fixture


def trial_args(paths):
    return [
        "--review-dir",
        str(paths.review_dir),
        "--app",
        str(paths.app),
        "--factory-ota1",
        str(paths.ota1),
        "--pretrial-nvs",
        str(paths.nvs),
        "--board-reference",
        str(paths.board_reference),
        "--port",
        "COM3",
    ]


def test_cli_needs_explicit_execution_and_all_approvals(review, monkeypatch, capsys):
    paths, _, approval = review

    def never(*_):
        pytest.fail("serial prerequisites ran without approved execution")

    monkeypatch.setattr(list_ports, "comports", never)
    monkeypatch.setattr("paid_trial_rom._load_esptool", never)
    with pytest.raises(SystemExit) as denied:
        operator_tool.main(trial_args(paths))
    assert denied.value.code == 2
    approval.unlink()
    assert operator_tool.main(["--execute", *trial_args(paths)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["approval_rejected"]
    assert not report["install_attempted"]
    assert not (paths.review_dir / "install-started.json").exists()


@pytest.mark.parametrize("occupied", [False, True])
def test_port_check_requests_an_exclusive_handle_and_closes_it(monkeypatch, occupied):
    events = []

    def open_handle(*args):
        events.append(("open", args))
        return -1 if occupied else 12

    def close_handle(handle):
        events.append(("close", handle))
        return 1

    fake = SimpleNamespace(
        CreateFile=open_handle,
        CloseHandle=close_handle,
        INVALID_HANDLE_VALUE=-1,
        GENERIC_READ=1,
        GENERIC_WRITE=2,
        OPEN_EXISTING=3,
        FILE_ATTRIBUTE_NORMAL=4,
    )
    monkeypatch.setattr(serial, "win32", fake, raising=False)
    assert operator_tool._windows_port_available("COM3") is not occupied
    assert events[0] == ("open", (r"\\.\COM3", 3, 0, None, 3, 4, None))
    assert events[1:] == ([] if occupied else [("close", 12)])


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


@pytest.mark.parametrize("outcome", ["ready", "replacement", "occupied", "ctrl_break"])
def test_cli_waits_for_original_usb_identity_and_restores_reviewed_ranges(
    review, monkeypatch, capsys, outcome
):
    paths, _, _ = review
    device = Tool(paths)
    operator = SimulatedOperator()
    original = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM3", serial_number="original")
    other = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM3", serial_number="other")
    checks = []
    break_signal = 21
    handlers = {break_signal: signal.SIG_DFL}
    delivered = []

    def register_handler(which, handler):
        previous = handlers[which]
        handlers[which] = handler
        return previous

    console_signals = SimpleNamespace(
        SIGBREAK=break_signal,
        signal=register_handler,
        default_int_handler=signal.default_int_handler,
    )
    monkeypatch.setattr(operator_tool, "signal", console_signals, raising=False)

    def ports():
        if not device.events:
            return [original]
        if ("trial", 1) not in device.events and operator.seconds < 1:
            return []  # Temporary USB removal immediately after the app boot reset.
        if ("trial", 1) not in device.events or operator.seconds < operator.unplug_at:
            return [original]
        if operator.seconds >= operator.reconnect_at:
            return [other if outcome == "replacement" else original]
        return []

    def run_pairing(arguments, *, timeout, check):
        assert device.events[-1] == ("close", 1)
        assert operator.seconds >= 1
        assert Path(arguments[1]).name == "scps_usb_cli.py"
        assert arguments[2:] == ["--port", "COM3", "--interactive"]
        assert 0 < timeout <= 145 and check is False
        operator.unplug_at, operator.reconnect_at = 2, 5
        device.events.append(("trial", 1))
        device.flash[0x9000] = b"trial changed the NVS"
        if outcome == "ctrl_break":
            handler = handlers[break_signal]
            delivered.append(handler)
            if callable(handler):
                handler(break_signal, None)
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

    def detect(port, **args):
        assert port == "COM3"
        return device.detect("mock-port", **args)

    def available(port):
        checks.append(port)
        return outcome != "occupied"

    monkeypatch.setattr("paid_trial_rom._load_esptool", lambda: (detect, Chip, device))
    monkeypatch.setattr(operator_tool, "_windows_port_available", available, raising=False)

    status = operator_tool.main(["--execute", *trial_args(paths)])
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert handlers[break_signal] is signal.SIG_DFL
    if outcome == "occupied":
        assert status == 2
        assert result["trial_failure"] == TrialStep.PREFLIGHT
        assert not result["install_attempted"]
        assert device.events == []
        assert checks == ["COM3"]
    elif outcome == "replacement":
        assert status == 3
        assert result["recovery_failure"] == TrialStep.REBIND_FOR_RESTORE
        assert not result["factory_boot_requested"]
        assert device.connections == 1
        assert device.flash[0x9000] != paths.nvs.read_bytes()
    else:
        if outcome == "ctrl_break":
            assert delivered == [signal.default_int_handler]
            assert status == 1
            assert result["trial_failure"] == TrialStep.BOOT_AND_RUN_ONE_TURN
        else:
            assert status == 0 and result["trial_failure"] is None
        assert result["factory_boot_requested"]
        assert device.flash[0x9000] == paths.nvs.read_bytes()
        assert checks == ["COM3", "COM3"]
        assert device.events[-2:] == [("reset", 2), ("close", 2)]
