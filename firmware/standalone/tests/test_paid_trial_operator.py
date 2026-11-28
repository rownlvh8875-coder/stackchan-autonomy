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
from test_paid_trial_binding import reboot_review as reboot_review_fixture  # noqa: E402
from test_paid_trial_binding import review as review_fixture  # noqa: E402
from test_paid_trial_binding import run_bound_paid_trial  # noqa: E402
from test_paid_trial_rom import Chip, Tool  # noqa: E402

review = review_fixture
reboot_review = reboot_review_fixture


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


@pytest.mark.parametrize("factory_changed_nvs", [False, True])
def test_cli_recovers_without_writes_or_pairing_after_possible_factory_boot(
    review, monkeypatch, capsys, factory_changed_nvs
):
    paths, _, _ = review
    result = run_bound_paid_trial(paths, lambda step, _: step is not TrialStep.REQUEST_FACTORY_BOOT)
    assert result.recovery_failure is TrialStep.REQUEST_FACTORY_BOOT
    device = Tool(paths)
    if factory_changed_nvs:
        device.flash[0x9000] = b"factory wrote a newer value"

    def detect(port, **kwargs):
        assert port == "COM3"
        return device.detect("mock-port", **kwargs)

    def forbidden(*_args, **_kwargs):
        pytest.fail("recovery must not attempt pairing or exercise a conversation")

    tty = SimpleNamespace(isatty=lambda: True)
    port = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM3", serial_number="original")
    monkeypatch.setattr(
        operator_tool, "sys", SimpleNamespace(platform="win32", stdin=tty, stdout=tty)
    )
    monkeypatch.setattr(
        operator_tool, "_windows_port_available", lambda selected: selected == "COM3"
    )
    monkeypatch.setattr(operator_tool, "import_module", forbidden)
    monkeypatch.setattr(operator_tool, "exercise_one_turn", forbidden)
    monkeypatch.setattr(list_ports, "comports", lambda: [port])
    monkeypatch.setattr("paid_trial_rom._load_esptool", lambda: (detect, Chip, device))

    status = operator_tool.main(["--recover", *trial_args(paths)])
    report = json.loads(capsys.readouterr().out)
    assert report["recovery_only"] and report["install_attempted"]
    assert not any(event[0] == "write" for event in device.events)
    assert ("verify", 1, 0x510000) in device.events and ("verify", 1, 0x9000) in device.events
    if factory_changed_nvs:
        assert status == 3 and report["recovery_failure"] == TrialStep.VERIFY_PRETRIAL_NVS
        assert not report["factory_boot_requested"] and ("reset", 1) not in device.events
    else:
        assert status == 0 and report["factory_boot_requested"]
        assert device.events[-2:] == [("reset", 1), ("close", 1)]


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


def test_buffered_confirmation_from_before_the_observation_cannot_pass():
    operator = SimulatedOperator(answer=None)
    buffered = iter(("Y",))
    operator.key = lambda: next(buffered, None)

    assert operator.run() is False
    assert operator.prompt("Hi StackChan")[2] == operator.unplug_at
    assert operator.prompt("다시 연결")[2] == operator.reconnect_at


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


@pytest.mark.parametrize(
    "outcome",
    [
        "ready",
        "saved_setup",
        "renumbered",
        "wrong_port",
        "replacement",
        "occupied",
        "ctrl_break",
        "reboot_ok",
        "reboot_budget",
        "reboot_stop",
        "reboot_usb",
        "reboot_wrong_board",
    ],
)
def test_cli_waits_for_original_usb_identity_and_restores_reviewed_ranges(
    review, monkeypatch, capsys, outcome, request
):
    combined = outcome.startswith("reboot_")
    paths, _, _ = request.getfixturevalue("reboot_review") if combined else review
    device = Tool(paths)
    operator = SimulatedOperator()
    original = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM3", serial_number="original")
    changed_port = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM4", serial_number="original")
    other = SimpleNamespace(vid=0x303A, pid=0x1001, device="COM3", serial_number="other")
    checks = []
    source_options = (
        ["--reuse-openai-env", str(paths.review_dir / "synthetic.env"), "--reuse-connected-wifi"]
        if outcome == "saved_setup"
        else []
    )
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
            if outcome == "wrong_port" or (outcome == "renumbered" and operator.seconds < 8):
                return [changed_port]
            return [other if outcome == "replacement" else original]
        return []

    def run_pairing(arguments, *, timeout, check):
        assert device.events[-1] == ("close", 1)
        assert operator.seconds >= 1
        assert Path(arguments[1]).name == "scps_usb_cli.py"
        assert arguments[2:] == [
            "--port",
            "COM3",
            "--interactive",
            "--failure-receipt",
            str(paths.review_dir / "setup-failure.json"),
            *source_options,
        ]
        assert 0 < timeout <= 145 and check is False
        operator.unplug_at = 2
        operator.reconnect_at = {
            "reboot_ok": 98,
            "reboot_budget": 70,
            "reboot_stop": 98,
            "reboot_usb": 6,
            "reboot_wrong_board": 98,
        }.get(outcome, 5)
        device.wrong_recovery_board = outcome == "reboot_wrong_board"
        device.events.append(("trial", 1))
        device.flash[0x9000] = b"trial changed the NVS"
        if outcome == "ctrl_break":
            handler = handlers[break_signal]
            delivered.append(handler)
            if callable(handler):
                handler(break_signal, None)
        return SimpleNamespace(returncode=0)

    tty = SimpleNamespace(isatty=lambda: True)
    console_stdout = sys.stdout

    class Console:
        platform = "win32"
        stdin = tty
        executable = sys.executable

        @property
        def stdout(self):
            # ROM log suppression replaces the live stream during port binding.
            return tty if sys.stdout is console_stdout else sys.stdout

    clock = SimpleNamespace(monotonic=lambda: operator.seconds, sleep=operator.advance)
    keys = {
        3: "1",
        68: "n" if outcome == "reboot_budget" else "2",
        75: "3",
        95: "n" if outcome == "reboot_stop" else "4",
    }
    keyboard = (
        SimpleNamespace(
            kbhit=lambda: operator.seconds in keys, getwch=lambda: keys.pop(operator.seconds)
        )
        if combined
        else SimpleNamespace(kbhit=lambda: operator.seconds >= 3, getwch=lambda: "y")
    )
    monkeypatch.setattr(operator_tool, "sys", Console())
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

    mode_args = ["--execute", "--reboot-trial"] if combined else ["--execute"]
    status = operator_tool.main([*mode_args, *trial_args(paths), *source_options])
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert handlers[break_signal] is signal.SIG_DFL
    if combined:
        assert result["trial_scope"] == "reboot_trial"
        if outcome == "reboot_wrong_board":
            assert status == 3 and result["recovery_failure"] == TrialStep.REBIND_FOR_RESTORE
            assert not result["factory_boot_requested"]
            assert [event for event in device.events if event[0] == "write"] == [
                ("write", 1, 0x510000),
            ]
            return
        assert status == (0 if outcome == "reboot_ok" else 1)
        assert result["trial_failure"] == (
            None if outcome == "reboot_ok" else TrialStep.BOOT_AND_RUN_REBOOT_TRIAL
        )
        assert result["factory_boot_requested"]
        assert [event for event in device.events if event[0] == "write"] == [
            ("write", 1, 0x510000),
            ("write", 2, 0x510000),
            ("write", 2, 0x9000),
        ]
        assert device.flash[0x510000] == paths.ota1.read_bytes()
        assert device.flash[0x9000] == paths.nvs.read_bytes()
        assert device.events[-2:] == [("reset", 2), ("close", 2)]
        return
    if outcome == "occupied":
        assert status == 2
        assert result["trial_failure"] == TrialStep.PREFLIGHT
        assert not result["install_attempted"]
        assert device.events == []
        assert checks == ["COM3"]
    elif outcome in ("replacement", "wrong_port"):
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
            if outcome == "renumbered":
                assert operator.seconds >= 8
        assert result["factory_boot_requested"]
        assert device.flash[0x9000] == paths.nvs.read_bytes()
        assert checks == ["COM3", "COM3"]
        assert device.events[-2:] == [("reset", 2), ("close", 2)]


@pytest.mark.parametrize(
    "failed_stage", [None, "before_reboot", "after_reboot", "standby", "stop", "usb", "held_key"]
)
def test_combined_exercise_requires_each_observation_and_returns_to_usb(failed_stage):
    operator = SimulatedOperator(reconnect_at=130)
    keys = {2: "1", 68: "2", 75: "3", 95: "4"}
    if failed_stage == "usb":
        operator.reconnect_at = 6
    elif failed_stage == "held_key":
        keys = dict.fromkeys(range(2, 130), "1")
    elif failed_stage is not None:
        denied_at = {"before_reboot": 2, "after_reboot": 68, "standby": 75, "stop": 95}[
            failed_stage
        ]
        keys[denied_at] = "n"
        operator.reconnect_at = denied_at + 4

    assert operator_tool.exercise_reboot_trial(
        operator.pair,
        operator.present,
        lambda: keys.pop(operator.seconds, None),
        operator.say,
        lambda: operator.seconds,
        operator.advance,
    ) is (failed_stage is None)
    assert operator.prompt("다시 연결")[2] <= operator.reconnect_at
    if failed_stage not in ("before_reboot", "usb"):
        assert operator.prompt("Enter your unlock code")[2] >= 62
    else:
        assert not any(
            event[0] == "prompt" and "Enter your unlock code" in event[1]
            for event in operator.events
        )
    if failed_stage == "held_key":
        assert not any(
            event[0] == "prompt" and "재부팅 뒤 첫" in event[1] for event in operator.events
        )
