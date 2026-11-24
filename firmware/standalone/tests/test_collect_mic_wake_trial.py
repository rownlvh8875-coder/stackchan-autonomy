"""No USB; simulated serial input exercises the one-START protocol."""

import json
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    import collect_mic_wake_trial

    return collect_mic_wake_trial


def test_speaker_prepare_cue_precedes_any_port_open(receiver, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["collector", "--review-dir", str(tmp_path), "--speaker"])
    monkeypatch.setattr(receiver, "verified_port", lambda *args, **kwargs: ("COM3", "a" * 64))

    def open_simulated(*args):
        assert capsys.readouterr().out.splitlines() == ["SPEAKER_PREPARE"]
        raise OSError("synthetic failure before any device communication")

    monkeypatch.setattr(receiver, "open_port", open_simulated)
    assert receiver.main() == 1
    assert not (tmp_path / "mic-receive-intent.json").exists()


@pytest.mark.parametrize(
    ("outcome", "expected_exit"), [("dma_and_mute_observed", 0), ("cleanup_failed", 1)]
)
def test_speaker_exit_requires_successful_playback_and_mute(
    receiver, monkeypatch, tmp_path, outcome, expected_exit
):
    monkeypatch.setattr(sys, "argv", ["collector", "--review-dir", str(tmp_path), "--speaker"])
    monkeypatch.setattr(receiver, "verified_port", lambda *args, **kwargs: ("COM3", "a" * 64))
    monkeypatch.setattr(receiver, "open_port", lambda *args: SimpleNamespace(close=lambda: None))
    report = {
        "speaker_probe": receiver.SPEAKER_PROTOCOL,
        "result": outcome,
        "operating_admission": False,
    }
    monkeypatch.setattr(receiver, "receive_once", lambda *args, **kwargs: report)
    assert receiver.main() == expected_exit
    assert json.loads((tmp_path / "speaker-result.json").read_bytes()) == report


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
        self.input = deque(
            item if isinstance(item, bytes) else json.dumps(item).encode("ascii") + b"\n"
            for item in records
        )
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


CONTROL_WAIT = {**WAIT, "mic_trial": "WAIT_WAKE_ONLY_CONTROL"}
CONTROL_CUE = {**QUESTION_CUE, "mic_trial": "QUIET_OBSERVATION_NOW"}


@pytest.mark.parametrize("outcome", ["no_endpoint", "stopped", "endpoint"])
def test_collect_wake_only_control_result(receiver, outcome):
    result = {**QUESTION, "result": outcome}
    port = FakeSerial([CONTROL_WAIT, LISTEN, CONTROL_CUE, WAKE_V2, result, HOLD])
    prompts = []
    collected = receiver.receive_once(
        port,
        lambda: prompts.append("wake"),
        announce_question=lambda: prompts.append("wait"),
        wake_only_control=True,
    )
    assert collected == {"wake": WAKE_V2, "question": result}
    assert prompts == ["wake", "wait"]
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize("wake_only,marker", [(True, QUESTION_WAIT), (False, CONTROL_WAIT)])
def test_question_and_control_challenges_are_not_interchangeable(receiver, wake_only, marker):
    port = FakeSerial([marker])
    with pytest.raises(ValueError):
        receiver.receive_once(
            port, lambda: None, announce_question=lambda: None, wake_only_control=wake_only
        )
    assert port.writes == [b"HELLO\n"]


@pytest.mark.parametrize("wake_only", [False, True])
@pytest.mark.parametrize("version", [3, 4])
def test_collects_wake_deadline_before_question_phase(receiver, wake_only, version):
    fault = {
        "mic_wake_trial": "MIC_WAKE_TRIAL_V3",
        "result": "fault",
        "stage": "capture_clock",
        "clock_reason": "capture_window_exceeded",
        "codec_cleanup_unverified": False,
        "operating_admission": False,
    }
    if version == 4:
        fault.update(
            mic_wake_trial="MIC_WAKE_TRIAL_V4",
            deadline_progress={
                "frames_read": 486,
                "model_calls": 151,
                "last_model_result": "none",
                "last_poll_step": "mic_read",
            },
        )
    question = {**QUESTION, "result": "not_run"}
    wait = CONTROL_WAIT if wake_only else QUESTION_WAIT
    port = FakeSerial([wait, LISTEN, fault, question, HOLD])
    assert receiver.receive_once(
        port,
        lambda: None,
        announce_question=lambda: pytest.fail("Unexpected question-phase prompt"),
        wake_only_control=wake_only,
    ) == {"wake": fault, "question": question}
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


def test_control_rejects_positive_question_cue(receiver):
    port = FakeSerial([CONTROL_WAIT, LISTEN, QUESTION_CUE])
    with pytest.raises(ValueError):
        receiver.receive_once(
            port,
            lambda: None,
            announce_question=lambda: pytest.fail("Unexpected question prompt"),
            wake_only_control=True,
        )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n", b"STOP\n"]


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
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, wake_only_control=True)

    manifest.update(
        kind="REVIEW_ONLY_WAKE_ONLY_CONTROL_V1",
        scope=receiver.WAKE_ONLY_CONTROL_SCOPE,
    )
    write("review-manifest.json", manifest)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, wake_only_control=True)
    write("approval.json", {**approval, "scope": receiver.WAKE_ONLY_CONTROL_SCOPE})
    assert receiver.verified_port(tmp_path, wake_only_control=True) == ("COM3", digest)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question=True)


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


ONLY_WAIT = {**WAIT, "mic_trial": "WAIT_QUESTION_ONLY_START"}
ONLY_CUE = {**QUESTION_CUE, "mic_trial": "QUESTION_ONLY_NOW"}
ONLY_REPORT = {**QUESTION, "mic_question_trial": "MIC_QUESTION_ONLY_TRIAL_V1"}


@pytest.mark.parametrize("outcome", ["endpoint", "no_endpoint", "stopped"])
def test_question_only_collects_no_wake_record(receiver, outcome):
    report = {**ONLY_REPORT, "result": outcome}
    port = FakeSerial([ONLY_WAIT, ONLY_CUE, report, HOLD])
    cues = []
    assert (
        receiver.receive_once(
            port,
            lambda: pytest.fail("Question-only trial has no wake cue"),
            announce_question=lambda: cues.append("question"),
            question_only=True,
        )
        == report
    )
    assert cues == ["question"]
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize(
    "tail",
    [
        [QUESTION_CUE, ONLY_REPORT],
        [ONLY_CUE, WAKE_V2, ONLY_REPORT],
        [ONLY_REPORT],
        [ONLY_CUE, {**ONLY_REPORT, "raw_pcm": [0]}],
        [ONLY_CUE, QUESTION],
        [ONLY_CUE, {**ONLY_REPORT, "result": "not_run"}],
    ],
)
def test_question_only_rejects_cross_mode_or_invalid_data(receiver, tail):
    port = FakeSerial([ONLY_WAIT, *tail, HOLD])
    with pytest.raises(ValueError):
        receiver.receive_once(
            port, lambda: None, announce_question=lambda: None, question_only=True
        )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n", b"STOP\n"]


def test_question_only_scope_is_separate(receiver, tmp_path):
    sha = "a" * 64
    manifest = {
        "port": "COM3",
        "image_sha256": sha,
        "kind": "REVIEW_ONLY_QUESTION_ONLY_TRIAL_V1",
        "scope": "ONE_QUESTION_ONLY_TRIAL_AND_OTA1_RESTORE",
        "expected_protocol": "MIC_QUESTION_ONLY_TRIAL_V1",
    }
    (tmp_path / "review-manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "install-verified.json").write_text(
        json.dumps(
            {
                "port": "COM3",
                "offset": 0x510000,
                "independent_verify_passed": True,
                "image_sha256": sha,
            }
        )
    )
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "approved": True,
                "image_sha256": sha,
                "scope": receiver.QUESTION_SCOPE,
            }
        )
    )
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question_only=True)
    approval.write_text(
        json.dumps(
            {
                "approved": True,
                "image_sha256": sha,
                "scope": manifest["scope"],
            }
        )
    )
    assert receiver.verified_port(tmp_path, question_only=True) == ("COM3", sha)
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question=True)


SILENT_TX_WAIT = {**WAIT, "mic_trial": "WAIT_SILENT_TX_LOCAL_START"}
SPEAKER_WAIT = {**WAIT, "mic_trial": "WAIT_SPEAKER_LOCAL_START"}
SPEAKER_REPORT = {
    "speaker_probe": "K151_SPEAKER_V1",
    "result": "dma_and_mute_observed",
    "operating_admission": False,
}
SILENT_TX_REPORT = {
    "tx_dma_probe": "K151_SILENT_TX_V1",
    "result": "two_descriptors_observed",
    "operating_admission": False,
}


@pytest.mark.parametrize(
    "outcome", ["dma_and_mute_observed", "stopped", "mute_confirmation_failed"]
)
def test_speaker_report_and_hold_without_voice_cue(receiver, outcome):
    report = SPEAKER_REPORT | {"result": outcome}
    port = FakeSerial([SPEAKER_WAIT, report, HOLD])
    assert receiver.receive_once(port, lambda: pytest.fail("Voice cue"), speaker=True) == report
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize("bad", [LISTEN, SILENT_TX_REPORT, SPEAKER_REPORT | {"raw_pcm": [0]}])
def test_speaker_rejects_foreign_report_or_pcm(receiver, bad):
    port = FakeSerial([SPEAKER_WAIT, bad, HOLD])
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None, speaker=True)
    assert port.writes[-1] == b"STOP\n"


def test_speaker_startup_report_requires_its_own_challenge_and_fixed_stage(receiver):
    protocol = receiver.SPEAKER_STARTUP_PROTOCOL
    wait = SPEAKER_WAIT | {"mic_trial": receiver.SPEAKER_CHALLENGES[protocol]}
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed",
        "startup_stage": "wait_clock",
    }
    port = FakeSerial([wait, report, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    for outcome in ("cleanup_failed", "dma_and_mute_observed"):
        stage = "wait_clock" if outcome == "cleanup_failed" else "none"
        terminal = report | {"result": outcome, "startup_stage": stage}
        assert (
            receiver.validate_output_report(terminal, speaker=True, speaker_protocol=protocol)
            == terminal
        )
    wrong = FakeSerial([SPEAKER_WAIT, report, HOLD])
    with pytest.raises((ValueError, TimeoutError)):
        receiver.receive_once(wrong, lambda: None, speaker=True, speaker_protocol=protocol)
    assert all(not write.startswith(b"START ") for write in wrong.writes)
    for invalid in (
        report | {"startup_stage": "none"},
        report | {"startup_stage": "unknown"},
        report | {"startup_stage": [1]},
        report | {"result": "dma_and_mute_observed"},
        report | {"raw_pcm": [0]},
        {key: value for key, value in report.items() if key != "startup_stage"},
    ):
        with pytest.raises(ValueError):
            receiver.validate_output_report(invalid, speaker=True, speaker_protocol=protocol)


def test_speaker_clock_report_preserves_exit_and_last_accepted_sample(receiver):
    protocol = receiver.SPEAKER_CLOCK_PROTOCOL
    wait = SPEAKER_WAIT | {"mic_trial": receiver.SPEAKER_CHALLENGES[protocol]}
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed",
        "startup_stage": "wait_clock",
        "clock_wait_exit": "startup_deadline",
        "clock_wait_last": "reference_missing",
    }
    port = FakeSerial([wait, report, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]
    cleanup_fault = report | {"result": "cleanup_failed"}
    assert (
        receiver.validate_output_report(cleanup_fault, speaker=True, speaker_protocol=protocol)
        == cleanup_fault
    )
    for invalid in (
        report | {"clock_wait_exit": "none"},
        report | {"clock_wait_last": "none"},
        report | {"clock_wait_last": "0x1234"},
        report | {"clock_wait_exit": ["startup_deadline"]},
        report | {"startup_stage": "codec_open"},
        {key: value for key, value in report.items() if key != "clock_wait_last"},
    ):
        with pytest.raises(ValueError):
            receiver.validate_output_report(invalid, speaker=True, speaker_protocol=protocol)


def test_speaker_protection_report_preserves_only_named_flags_from_a_single_start(receiver):
    protocol = "K151_SPEAKER_V4"
    wait = SPEAKER_WAIT | {"mic_trial": "WAIT_SPEAKER_PROTECTION_LOCAL_START"}
    flags = {
        "ovp2": False,
        "undervoltage": True,
        "boost_overcurrent": False,
        "ovp": False,
        "amplifier_overcurrent": True,
        "overtemperature": False,
    }
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed",
        "startup_stage": "wait_clock",
        "clock_wait_exit": "protection_active",
        "clock_wait_last": "stable",
        "protection": flags,
    }
    port = FakeSerial([wait, report, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]

    clock_clear = dict.fromkeys(flags, False)
    for valid in (
        report | {"result": "cleanup_failed"},
        report
        | {"startup_stage": "wait_switching", "clock_wait_exit": "none", "clock_wait_last": "none"},
        report | {"clock_wait_exit": "startup_deadline", "protection": clock_clear},
    ):
        assert (
            receiver.validate_output_report(valid, speaker=True, speaker_protocol=protocol) == valid
        )

    for invalid in (
        report | {"protection": clock_clear},
        report | {"protection": flags | {"raw_sysst": 0x4019}},
        report | {"protection": flags | {"undervoltage": 1}},
        report | {"protection": None},
        report | {"clock_wait_exit": "status_read_failed"},
        report | {"clock_wait_last": "unobserved"},
        report
        | {"startup_stage": "codec_open", "clock_wait_exit": "none", "clock_wait_last": "none"},
        {key: value for key, value in report.items() if key != "protection"},
    ):
        with pytest.raises(ValueError):
            receiver.validate_output_report(invalid, speaker=True, speaker_protocol=protocol)

    for expected, challenge in (
        (receiver.SPEAKER_CLOCK_PROTOCOL, wait),
        (protocol, SPEAKER_WAIT | {"mic_trial": "WAIT_SPEAKER_CLOCK_LOCAL_START"}),
    ):
        port = FakeSerial([challenge])
        with pytest.raises(ValueError):
            receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=expected)
        assert port.writes == [b"HELLO\n"]


@pytest.mark.parametrize(
    "protocol,standby_uvls,reset_uvls",
    [
        ("K151_SPEAKER_V5", None, None),
        ("K151_SPEAKER_V6", False, None),
        ("K151_SPEAKER_V6", True, None),
        ("K151_SPEAKER_V7", False, [True, False, False]),
        ("K151_SPEAKER_V7", True, [False, True, True]),
        ("K151_SPEAKER_V7", True, [None, False, True]),
    ],
)
def test_speaker_vdd_requires_accepted_uvls_and_rejects_raw_data(
    receiver, protocol, standby_uvls, reset_uvls
):
    wait = SPEAKER_WAIT | {"mic_trial": receiver.SPEAKER_CHALLENGES[protocol]}
    protection = {
        "ovp2": False,
        "undervoltage": True,
        "boost_overcurrent": False,
        "ovp": False,
        "amplifier_overcurrent": False,
        "overtemperature": False,
    }
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed",
        "startup_stage": "wait_clock",
        "clock_wait_exit": "protection_active",
        "clock_wait_last": "stable",
        "protection": protection,
        "uvls_after_clock_us": 1200,
        "vdd_after_uvls_us": 700,
        "startup_vdd": "sampled",
        "startup_vdd_mv": 2497,
    }
    if standby_uvls is not None:
        report["standby_uvls"] = standby_uvls
    if reset_uvls is not None:
        report["reset_uvls"] = reset_uvls
    wire = json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n"
    assert len(wire) <= receiver.WIRE_LIMIT
    port = FakeSerial([wait, wire, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]
    for invalid in (
        report | {"uvls_after_clock_us": 100_000},
        report | {"uvls_after_clock_us": True},
        report | {"uvls_after_clock_us": -1},
        report | {"vdd_after_uvls_us": -1},
        report | {"vdd_after_uvls_us": 99_000},
        report | {"startup_vdd_mv": 0},
        report | {"startup_vdd": "read_failed"},
        report | {"protection": protection | {"amplifier_overcurrent": True}},
        report | {"raw_vdd": 0x01A8},
    ):
        with pytest.raises(ValueError):
            receiver.validate_output_report(invalid, speaker=True, speaker_protocol=protocol)
    skipped = report | {
        "protection": protection | {"amplifier_overcurrent": True},
        "startup_vdd": "skipped",
        "vdd_after_uvls_us": -1,
        "startup_vdd_mv": 0,
    }
    assert (
        receiver.validate_output_report(skipped, speaker=True, speaker_protocol=protocol) == skipped
    )
    if standby_uvls is not None:
        for invalid_baseline in (None, 0, "false"):
            with pytest.raises(ValueError):
                receiver.validate_output_report(
                    report | {"standby_uvls": invalid_baseline},
                    speaker=True,
                    speaker_protocol=protocol,
                )
        failed_readback = {
            **report,
            "startup_stage": "i2s_enable",
            "clock_wait_exit": "none",
            "clock_wait_last": "none",
            "protection": protection | {"undervoltage": False},
            "uvls_after_clock_us": -1,
            "vdd_after_uvls_us": -1,
            "startup_vdd": "not_requested",
            "startup_vdd_mv": 0,
            "standby_uvls": None,
        }
        if reset_uvls is not None:
            failed_readback["reset_uvls"] = [None, None, None]
        assert (
            receiver.validate_output_report(
                failed_readback, speaker=True, speaker_protocol=protocol
            )
            == failed_readback
        )
        with pytest.raises(ValueError):
            receiver.validate_output_report(
                failed_readback | {"standby_uvls": False}, speaker=True, speaker_protocol=protocol
            )
        if reset_uvls is not None:
            for invalid_reset in (None, [False, False], [0, True, True], [False, None, False]):
                with pytest.raises(ValueError):
                    receiver.validate_output_report(
                        report | {"reset_uvls": invalid_reset},
                        speaker=True,
                        speaker_protocol=protocol,
                    )
            with pytest.raises(ValueError):
                receiver.validate_output_report(
                    failed_readback | {"reset_uvls": reset_uvls},
                    speaker=True,
                    speaker_protocol=protocol,
                )


@pytest.mark.parametrize("followup", [(True, 570), (False, 570), (None, -1)])
def test_speaker_vdd_followup_preserves_the_first_protection(receiver, followup):
    protocol = "K151_SPEAKER_V8"
    wait = SPEAKER_WAIT | {"mic_trial": receiver.SPEAKER_CHALLENGES[protocol]}
    protection = dict.fromkeys(receiver.SPEAKER_PROTECTION_FLAGS, False)
    protection["undervoltage"] = True
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed",
        "startup_stage": "wait_clock",
        "clock_wait_exit": "protection_active",
        "clock_wait_last": "internal_unstable",
        "protection": protection,
        "standby_uvls": True,
        "reset_uvls": [True, True, True],
        "vdd": [60_000, 10_000, "sampled", 4370, *followup],
    }
    wire = json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n"
    assert len(wire) < receiver.WIRE_LIMIT
    port = FakeSerial([wait, wire, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]
    for invalid in (
        [60_000, 10_000, "sampled", 4370],
        [60_000, 10_000, "sampled", 4370, None, 0],
        [60_000, 10_000, "sampled", 4370, 0, 570],
        [60_000, 10_000, "sampled", 4370, False, True],
        [60_000, 10_000, "sampled", 4370, False, 30_000],
        [60_000, 10_000, "read_failed", 0, False, 570],
        [60_000, -1, "skipped", 0, True, 570],
    ):
        with pytest.raises(ValueError):
            receiver.validate_output_report(
                report | {"vdd": invalid}, speaker=True, speaker_protocol=protocol
            )
    no_fault = report | {
        "result": "dma_and_mute_observed",
        "startup_stage": "none",
        "clock_wait_exit": "none",
        "clock_wait_last": "none",
        "protection": protection | {"undervoltage": False},
        "standby_uvls": None,
        "reset_uvls": [None, None, None],
        "vdd": [-1, -1, "not_requested", 0, None, -1],
    }
    assert (
        receiver.validate_output_report(no_fault, speaker=True, speaker_protocol=protocol)
        == no_fault
    )


@pytest.mark.parametrize(
    "stage, settling",
    [
        ("none", [-1, -1]),
        ("none", [570, 2570]),
        ("wait_clock", [570, -1]),
        ("pre_amplifier_status", [570, -1]),
        ("pre_amplifier_status", [-1, -1]),
        ("wait_switching", [570, 2570]),
    ],
)
def test_speaker_settling_records_power_readiness_separately_from_protection(
    receiver, stage, settling
):
    protocol = "K151_SPEAKER_V9"
    wait = SPEAKER_WAIT | {"mic_trial": receiver.SPEAKER_CHALLENGES[protocol]}
    active = stage != "none"
    wait_fault = stage == "wait_clock"
    protection = dict.fromkeys(receiver.SPEAKER_PROTECTION_FLAGS, False)
    protection["undervoltage"] = active
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": "amplifier_start_failed" if active else "dma_and_mute_observed",
        "startup_stage": stage,
        "clock_wait_exit": "protection_active" if wait_fault else "none",
        "clock_wait_last": "stable" if wait_fault else "none",
        "protection": protection,
        "standby_uvls": True if wait_fault else None,
        "reset_uvls": [True, True, True] if wait_fault else [None, None, None],
        "vdd": [2570, 579, "sampled", 4482, False, 560]
        if wait_fault
        else [-1, -1, "not_requested", 0, None, -1],
        "settling_uvls": settling,
    }
    wire = json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n"
    assert len(wire) < receiver.WIRE_LIMIT
    port = FakeSerial([wait, wire, HOLD])
    assert (
        receiver.receive_once(port, lambda: None, speaker=True, speaker_protocol=protocol) == report
    )
    for invalid in ([2000, 2570], [570, 1999], [-1, 2570], [True, -1], [570]):
        with pytest.raises(ValueError):
            receiver.validate_output_report(
                report | {"settling_uvls": invalid}, speaker=True, speaker_protocol=protocol
            )
    if wait_fault or stage == "pre_amplifier_status":
        with pytest.raises(ValueError):
            receiver.validate_output_report(
                report | {"settling_uvls": [570, 2570]}, speaker=True, speaker_protocol=protocol
            )
    if wait_fault:
        for early_vdd in (
            [300, -1, "skipped", 0, None, -1],
            [1200, 579, "sampled", 4482, False, 560],
        ):
            with pytest.raises(ValueError):
                receiver.validate_output_report(
                    report | {"vdd": early_vdd}, speaker=True, speaker_protocol=protocol
                )
        mixed_fault = report | {
            "protection": protection | {"amplifier_overcurrent": True},
            "vdd": [1200, -1, "skipped", 0, None, -1],
        }
        assert (
            receiver.validate_output_report(mixed_fault, speaker=True, speaker_protocol=protocol)
            == mixed_fault
        )


@pytest.mark.parametrize(
    ("version", "outcome", "end"),
    [
        (10, "cleanup_failed", [2, 9]),
        (10, "mute_confirmation_failed", [1, 3]),
        (10, "transfer_failed", [0, 0]),
        (10, "dma_and_mute_observed", [2, 0]),
        (11, "cleanup_failed", [1, 19]),
        (11, "mute_confirmation_failed", [1, 20]),
        (12, "cleanup_failed", [1, 21]),
        (12, "mute_confirmation_failed", [1, 22]),
        (12, "cleanup_failed", [1, 24]),
        (12, "stopped", [1, 21]),
        (13, "mute_confirmation_failed", [1, 25]),
        (13, "stopped", [1, 21]),
    ],
)
def test_speaker_cleanup_preserves_playback_progress(receiver, version, outcome, end):
    protocol = f"K151_SPEAKER_V{version}"
    report = SPEAKER_REPORT | {
        "speaker_probe": protocol,
        "result": outcome,
        "startup_stage": "none",
        "clock_wait_exit": "none",
        "clock_wait_last": "none",
        "protection": dict.fromkeys(receiver.SPEAKER_PROTECTION_FLAGS, False),
        "standby_uvls": None,
        "reset_uvls": [None, None, None],
        "vdd": [-1, -1, "not_requested", 0, None, -1],
        "settling_uvls": [-1, -1] if outcome == "stopped" else [558, 7847],
        "end": end,
    }
    wire = json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n"
    assert len(wire) < receiver.WIRE_LIMIT
    challenge = {
        10: "WAIT_SPEAKER_CLEANUP_LOCAL_START",
        11: "WAIT_SPEAKER_STANDBY_CHECK_LOCAL_START",
        12: "WAIT_SPEAKER_MUTE_SETTLE_LOCAL_START",
        13: "WAIT_SPEAKER_AMP_OFF_LOCAL_START",
    }[version]
    wait = SPEAKER_WAIT | {"mic_trial": challenge}
    assert (
        receiver.receive_once(
            FakeSerial([wait, wire, HOLD]), lambda: None, speaker=True, speaker_protocol=protocol
        )
        == report
    )
    foreign = [2, 20] if version == 10 else [1, 25] if version == 12 else [1, 3]
    for invalid in ([3, 0], [True, 0], [2, 99], [0], foreign):
        with pytest.raises(ValueError):
            receiver.validate_output_report(
                report | {"end": invalid}, speaker=True, speaker_protocol=protocol
            )


@pytest.mark.parametrize(
    "outcome", ["two_descriptors_observed", "stopped", "timeout", "cleanup_failed"]
)
def test_silent_tx_is_single_start_and_collects_hold(receiver, outcome):
    report = SILENT_TX_REPORT | {"result": outcome}
    port = FakeSerial([SILENT_TX_WAIT, report, HOLD])
    assert (
        receiver.receive_once(
            port, lambda: pytest.fail("Silent TX has no audio cue"), silent_tx=True
        )
        == report
    )
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n"]


@pytest.mark.parametrize(
    "tail",
    [
        [LISTEN, SILENT_TX_REPORT, HOLD],
        [ONLY_CUE, HOLD],
        [ONLY_REPORT, HOLD],
        [WAKE_V2, HOLD],
        [HOLD],
        [SILENT_TX_REPORT, SILENT_TX_REPORT, HOLD],
        [SILENT_TX_REPORT | {"raw_pcm": [0]}, HOLD],
        [SILENT_TX_REPORT | {"result": "invalid"}, HOLD],
        [SILENT_TX_REPORT | {"operating_admission": 0}, HOLD],
        [SILENT_TX_REPORT | {"tx_dma_probe": "K151_SILENT_TX_V2"}, HOLD],
    ],
)
def test_silent_tx_rejects_voice_modes_or_invalid_reports(receiver, tail):
    port = FakeSerial([SILENT_TX_WAIT, *tail])
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None, silent_tx=True)
    assert port.writes == [b"HELLO\n", b"START 1234ABCD\n", b"STOP\n"]


@pytest.mark.parametrize("challenge, silent_tx", [(SILENT_TX_WAIT, False), (ONLY_WAIT, True)])
def test_silent_tx_challenge_cannot_start_the_wrong_image(receiver, challenge, silent_tx):
    port = FakeSerial([challenge])
    with pytest.raises(ValueError):
        receiver.receive_once(port, lambda: None, silent_tx=silent_tx)
    assert port.writes == [b"HELLO\n"]


@pytest.mark.parametrize(
    "speaker_protocol",
    [
        None,
        "K151_SPEAKER_V1",
        "K151_SPEAKER_V2",
        "K151_SPEAKER_V3",
        "K151_SPEAKER_V4",
        "K151_SPEAKER_V5",
        "K151_SPEAKER_V6",
        "K151_SPEAKER_V7",
        "K151_SPEAKER_V8",
        "K151_SPEAKER_V9",
    ],
)
def test_output_trial_binds_approval_and_install_to_exact_review(
    receiver, tmp_path, speaker_protocol
):
    speaker = speaker_protocol is not None
    digest = "a" * 64
    scope = receiver.SPEAKER_SCOPE if speaker else receiver.SILENT_TX_SCOPE
    selection = {"speaker": speaker, "silent_tx": not speaker}
    if speaker:
        selection["speaker_protocol"] = speaker_protocol
    receipt = {"approved": True, "scope": scope, "image_sha256": digest, "review_id": tmp_path.name}
    installed = {
        "port": "COM3",
        "offset": 0x510000,
        "independent_verify_passed": True,
        "image_sha256": digest,
        "review_id": tmp_path.name,
    }
    manifest = {
        "kind": (
            receiver.SPEAKER_REVIEW_KINDS[speaker_protocol]
            if speaker
            else "REVIEW_ONLY_SILENT_TX_PROBE_V1"
        ),
        "expected_protocol": speaker_protocol if speaker else receiver.SILENT_TX_PROTOCOL,
        "scope": scope,
        "port": "COM3",
        "image_sha256": digest,
        "review_id": tmp_path.name,
    }
    if speaker:
        manifest["operator_mode"] = receipt["operator_mode"] = "SYNTHETIC_SPEAKER_ONLY"
    for name, record in (
        ("review-manifest", manifest),
        ("approval", receipt),
        ("install-verified", installed),
    ):
        (tmp_path / f"{name}.json").write_text(json.dumps(record))
    assert receiver.verified_port(tmp_path, **selection) == ("COM3", digest)
    for name, record in (("approval", receipt), ("install-verified", installed)):
        file = tmp_path / f"{name}.json"
        file.write_text(json.dumps(record | {"review_id": "previous-review"}))
        with pytest.raises(ValueError):
            receiver.verified_port(tmp_path, **selection)
        file.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        receiver.verified_port(tmp_path, question_only=True)
    if speaker:
        wrong_protocol = (
            receiver.SPEAKER_PROTOCOL
            if speaker_protocol == receiver.SPEAKER_STARTUP_PROTOCOL
            else receiver.SPEAKER_STARTUP_PROTOCOL
        )
        with pytest.raises(ValueError):
            receiver.verified_port(tmp_path, speaker=True, speaker_protocol=wrong_protocol)
        (tmp_path / "approval.json").write_text(
            json.dumps(receipt | {"operator_mode": "SILENT_TX_NO_AUDIO"})
        )
        with pytest.raises(ValueError):
            receiver.verified_port(tmp_path, **selection)
