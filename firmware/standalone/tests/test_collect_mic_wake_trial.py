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


QUESTION_WAIT = {**WAIT, "mic_trial": "WAIT_QUESTION_LOCAL_START"}
QUESTION_CUE = {"mic_trial": "QUESTION_NOW", "operating_admission": False}
WAKE_V2 = {
    **REPORT,
    "mic_wake_trial": "MIC_WAKE_TRIAL_V2",
    "stage": "complete",
    "codec_cleanup_unverified": False,
}
QUESTION = {
    "mic_question_trial": "MIC_QUESTION_TRIAL_V1",
    "result": "endpoint",
    "codec_cleanup_unverified": False,
    "operating_admission": False,
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


def test_pre_listen_fault_with_stage_survives_collection(receiver):
    fault = {
        "mic_wake_trial": "MIC_WAKE_TRIAL_V2",
        "result": "fault",
        "operating_admission": False,
        "stage": "board_power",
        "codec_cleanup_unverified": False,
    }
    port = FakeSerial([WAIT, fault, HOLD])
    assert receiver.receive_once(port, lambda: pytest.fail("Unexpected listen prompt")) == fault


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


def test_collect_question_without_audio(receiver):
    port = FakeSerial([QUESTION_WAIT, LISTEN, QUESTION_CUE, WAKE_V2, QUESTION, HOLD])
    prompts = []
    report = receiver.receive_once(
        port, lambda: prompts.append("wake"), announce_question=lambda: prompts.append("question")
    )
    assert report == {"wake": WAKE_V2, "question": QUESTION}
    assert prompts == ["wake", "question"]
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize(
    ("result", "cleanup"), [("quiet_timeout", False), ("read_failed", False), ("read_failed", True)]
)
def test_collect_question_outcome_without_prompt(receiver, result, cleanup):
    outcome = {**QUESTION, "result": result, "codec_cleanup_unverified": cleanup}
    port = FakeSerial([QUESTION_WAIT, LISTEN, WAKE_V2, outcome, HOLD])
    report = receiver.receive_once(
        port, lambda: None, announce_question=lambda: pytest.fail("Question cue before quiet")
    )
    assert report == {"wake": WAKE_V2, "question": outcome}
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize(
    "records",
    [
        [LISTEN, WAKE_V2, QUESTION],
        [LISTEN, QUESTION_CUE, WAKE_V2, {**QUESTION, "result": "quiet_timeout"}],
        [
            LISTEN,
            WAKE_V2,
            {**QUESTION, "result": "quiet_timeout", "codec_cleanup_unverified": True},
        ],
        [LISTEN, QUESTION_CUE, WAKE_V2, {**QUESTION, "pcm": [42]}],
        [LISTEN, QUESTION_CUE, WAKE_V2, {**QUESTION, "codec_cleanup_unverified": True}],
        [LISTEN, QUESTION_CUE, WAKE_V2, {**QUESTION, "result": "not_run"}],
        [LISTEN, QUESTION_CUE, WAKE_V2, HOLD],
        [LISTEN, QUESTION_CUE, WAKE_V2, QUESTION, QUESTION],
        [LISTEN, QUESTION_CUE, QUESTION_CUE],
        [QUESTION_CUE],
    ],
)
def test_question_protocol_fails_closed(receiver, records):
    port = FakeSerial([QUESTION_WAIT, *records, HOLD])
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None, announce_question=lambda: None)
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n", b"STOP\n"]


@pytest.mark.parametrize("question", [False, True])
def test_other_trial_cannot_receive_start(receiver, question):
    port = FakeSerial([WAIT if question else QUESTION_WAIT])
    cue = (lambda: None) if question else None
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None, announce_question=cue)
    assert port.writes == [b"HELLO\n"]


def test_question_requires_its_own_verified_approval(receiver, tmp_path):
    digest = "a" * 64
    manifest = {"image_sha256": digest, "port": "COM3"}
    approval = {"approved": True, "image_sha256": digest, "scope": receiver.SCOPE}
    installed = {
        **manifest,
        "independent_verify_passed": True,
        "offset": 0x510000,
    }

    def write(name, record):
        (tmp_path / name).write_text(json.dumps(record), encoding="utf-8")

    write("review-manifest.json", manifest)
    write("approval.json", approval)
    write("install-verified.json", installed)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question=True)

    manifest.update(
        kind="REVIEW_ONLY_MIC_QUESTION_TRIAL_V1",
        expected_protocol="MIC_QUESTION_TRIAL_V1",
        scope="ONE_MIC_QUESTION_TRIAL_AND_OTA1_RESTORE",
    )
    write("review-manifest.json", manifest)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question=True)
    write("approval.json", {**approval, "scope": manifest["scope"]})
    assert receiver.verified_port(tmp_path, question=True) == ("COM3", digest)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path)


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
