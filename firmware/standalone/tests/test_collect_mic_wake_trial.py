"""No USB; simulated serial input exercises the one-START protocol."""

import json
from collections import deque
from pathlib import Path

import pytest


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    import collect_mic_wake_trial

    return collect_mic_wake_trial


WAIT = {"mic_trial": "WAIT_LOCAL_START", "nonce": "1234ABCD", "wait_ms": 60000}
LISTEN = {"mic_trial": "LISTEN_NOW", "operating_admission": False}
HOLD = {"mic_trial": "HOLD_UNTIL_RESET", "operating_admission": False}
REPORT = {
    "mic_wake_trial": "MIC_WAKE_TRIAL_V1",
    "result": "detected",
    "operating_admission": False,
    "frames_read": 10,
    "all_zero_frames": 2,
    "full_scale_samples": 0,
}


class FakeSerial:
    def __init__(self, records):
        self.input = deque(json.dumps(item).encode("ascii") + b"\n" for item in records)
        self.writes = []

    def read_until(self, expected, size):
        assert expected == b"\n" and size == 512
        return self.input.popleft()

    def write(self, value):
        self.writes.append(value)
        return len(value)


def test_single_start_and_only_allowlisted_report(receiver):
    port = FakeSerial([{"token": "discarded"}, WAIT, LISTEN, REPORT, HOLD])
    prompts = []
    assert receiver.receive_once(port, lambda: prompts.append(True)) == REPORT
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]
    assert prompts == [True]


def test_lost_challenge_request_and_duplicate_reply_still_send_one_start(receiver):
    port = FakeSerial([WAIT, WAIT, LISTEN, REPORT, HOLD])
    port.input.appendleft(b"")
    now = 0.0
    original = port.read_until

    def read_until(expected, size):
        nonlocal now
        now += 0.6
        return original(expected, size)

    port.read_until = read_until
    assert receiver.receive_once(port, lambda: None, clock=lambda: now) == REPORT
    assert port.writes == [b"HELLO\n", b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize(
    "records,start_sent",
    [
        ([REPORT], False),
        ([{**WAIT, "nonce": "00000000"}], False),
        ([WAIT, WAIT], True),
        ([WAIT, REPORT], True),
        ([WAIT, LISTEN, {**REPORT, "raw_pcm": "discarded"}], True),
        ([WAIT, LISTEN, HOLD], True),
    ],
)
def test_protocol_error_cannot_repeat_start_or_return_audio(receiver, records, start_sent):
    port = FakeSerial(records)
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None)
    assert port.writes == [b"HELLO\n"] + ([b"START 1234ABCD\n", b"STOP\n"] if start_sent else [])


def test_open_waits_for_port_to_return_without_toggling_control_lines(receiver):
    class SerialModule:
        SerialException = OSError
        opened = 0

        class Serial:
            def __init__(self, **kwargs):
                assert kwargs["port"] is None

            def open(self):
                assert self.port == "COM3" and not self.dtr and not self.rts
                SerialModule.opened += 1
                if SerialModule.opened == 1:
                    raise OSError

            def close(self):
                assert SerialModule.opened == 1

    waits = []
    port = receiver.open_port(SerialModule, "COM3", clock=lambda: 0, wait=waits.append)
    assert port.port == "COM3" and SerialModule.opened == 2 and len(waits) == 1
