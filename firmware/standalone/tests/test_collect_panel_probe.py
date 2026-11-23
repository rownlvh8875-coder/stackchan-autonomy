"""Exercise the panel collector on synthetic serial traffic only."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import collect_panel_probe as probe  # noqa: E402

CHALLENGE = b'{"probe":"WAIT_LOCAL_START","nonce":"C07ACAFE"}\n'


class Port:
    def __init__(self, initial=(), callback=None):
        self.messages = list(initial)
        self.callback = callback
        self.now = 0.0
        self.writes = []

    def read_until(self, *, expected, size):
        self.now += 0.1
        assert expected == b"\n" and 0 < size <= 512
        return self.messages.pop(0) if self.messages else b""

    def write(self, data):
        self.writes.append(data)
        if self.callback:
            self.callback(self, data)
        return len(data)


def test_delayed_boot_and_duplicate_challenge_still_send_only_one_start():
    def respond(port, data):
        if data == b"HELLO\n" and port.writes.count(data) == 2:
            port.messages.extend([CHALLENGE[:12], CHALLENGE[12:], CHALLENGE])
        if data == b"START C07ACAFE\n":
            for stage in probe.STAGES:
                port.messages.append(json.dumps({"probe": stage}).encode("ascii") + b"\n")
            port.messages.extend(
                [
                    b'{"result":"DISPLAY_STOP_LATCHED","cleanup":true,"operating_admission":false}\n',
                    b'{"probe":"HOLD_UNTIL_RESET","operating_admission":false}\n',
                ]
            )

    port = Port(callback=respond)
    notices = []
    reserved_at = []
    result = probe.receive_once(
        port, notices.append, lambda: reserved_at.append(len(port.writes)), lambda: port.now
    )
    assert port.writes == [b"HELLO\n", b"HELLO\n", b"START C07ACAFE\n"]
    assert reserved_at == [2]
    assert result["start_attempted"] and result["usb_ready"] and result["hold_observed"]
    assert result["result"] == "DISPLAY_STOP_LATCHED"
    assert len(notices) == 3


@pytest.mark.parametrize(
    ("initial", "reason", "boot_seen", "usb_ready"),
    [
        ([], "no_boot_or_usb_reply", False, False),
        ([probe.PROTOCOL.encode() + b"\n"], "challenge_timeout", True, False),
        (
            [b'{"probe":"PANEL_USB_READY","operating_admission":false}\n'],
            "challenge_timeout",
            False,
            True,
        ),
        ([b'{"result":"USB_SETUP_FAILED"}\n'], "device_usb_setup_failed", False, False),
    ],
)
def test_failed_handshake_keeps_fixed_evidence_without_start(initial, reason, boot_seen, usb_ready):
    port = Port(initial)
    with pytest.raises(probe.PanelProbeFailure) as error:
        probe.receive_once(port, lambda _: None, lambda: pytest.fail("START"), lambda: port.now)
    assert error.value.report == {
        "failure": reason,
        "boot_seen": boot_seen,
        "usb_ready": usb_ready,
        "start_attempted": False,
        "stages": [],
    }
    assert port.now < 8.2 and port.writes[-1] == b"STOP\n"


def test_challenge_received_after_deadline_cannot_send_start():
    class LateReply(Port):
        def read_until(self, **kwargs):
            self.now = 8.01
            return CHALLENGE

    port = LateReply()
    with pytest.raises(probe.PanelProbeFailure):
        probe.receive_once(
            port, lambda _: None, lambda: pytest.fail("late START"), lambda: port.now
        )
    assert port.writes == [b"HELLO\n", b"STOP\n"]


@pytest.mark.parametrize("stop_only", [False, True])
def test_screen_stop_only_requires_its_own_challenge_and_one_stage(stop_only):
    challenge = CHALLENGE.replace(b"WAIT_LOCAL_START", b"WAIT_SCREEN_STOP_START")

    def respond(port, data):
        if data == b"HELLO\n":
            port.messages.append(challenge)
        if data == b"START C07ACAFE\n":
            port.messages.extend(
                [
                    b'{"probe":"WAIT_SCREEN_STOP"}\n',
                    b'{"result":"DISPLAY_STOP_LATCHED","cleanup":true,"operating_admission":false}\n',
                    b'{"probe":"HOLD_UNTIL_RESET","operating_admission":false}\n',
                ]
            )

    port = Port(callback=respond)
    if not stop_only:
        with pytest.raises(probe.PanelProbeFailure):
            probe.receive_once(
                port, lambda _: None, lambda: pytest.fail("cross-mode START"), lambda: port.now
            )
        assert b"START C07ACAFE\n" not in port.writes
        return
    cues = []
    result = probe.receive_once(port, cues.append, lambda: None, lambda: port.now, stop_only=True)
    assert result["stages"] == ["WAIT_SCREEN_STOP"]
    assert cues == [probe.STAGES["WAIT_SCREEN_STOP"]]
    assert result["result"] == "DISPLAY_STOP_LATCHED"
    assert port.writes == [b"HELLO\n", b"START C07ACAFE\n"]


def test_serial_open_failure_is_distinct_and_never_records_start(tmp_path, monkeypatch):
    image = tmp_path / "artifact/k151_panel_probe.bin"
    image.parent.mkdir()
    image.write_bytes(b"synthetic image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    base = {"image_sha256": digest, "review_id": tmp_path.name, "port": "COM3"}
    scope = {"scope": probe.SCOPE, "operator_mode": probe.MODE}
    for filename, record in {
        "review-manifest.json": {
            **scope,
            "kind": probe.KIND,
            "expected_protocol": probe.PROTOCOL,
            "write_bytes": image.stat().st_size,
        },
        "approval.json": {**scope, "approved": True},
        "install-verified.json": {"independent_verify_passed": True, "offset": 0x510000},
    }.items():
        (tmp_path / filename).write_text(json.dumps({**base, **record}), encoding="utf-8")

    def fail_open():
        raise OSError("stub detail is private")

    monkeypatch.setitem(
        sys.modules, "serial", SimpleNamespace(Serial=lambda **_: SimpleNamespace(open=fail_open))
    )
    monkeypatch.setattr(sys, "argv", ["collect_panel_probe.py", "--review-dir", str(tmp_path)])
    assert probe.main() == 1
    assert json.loads((tmp_path / "panel-result.json").read_text()) == {
        "failure": "serial_open_failed"
    }
    assert not (tmp_path / "panel-trial-intent.json").exists()


def test_stop_only_rejects_prior_panel_approval(tmp_path):
    image = tmp_path / "artifact/k151_screen_stop_probe.bin"
    image.parent.mkdir()
    image.write_bytes(b"synthetic STOP-only image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    base = {"image_sha256": digest, "review_id": tmp_path.name, "port": "COM3"}
    records = {
        "review-manifest.json": {
            "scope": probe.STOP_SCOPE,
            "operator_mode": probe.STOP_MODE,
            "kind": probe.STOP_KIND,
            "expected_protocol": probe.STOP_PROTOCOL,
            "write_bytes": image.stat().st_size,
        },
        "approval.json": {"scope": probe.SCOPE, "operator_mode": probe.MODE, "approved": True},
        "install-verified.json": {"independent_verify_passed": True, "offset": 0x510000},
    }
    for filename, record in records.items():
        (tmp_path / filename).write_text(json.dumps({**base, **record}), encoding="utf-8")
    with pytest.raises(ValueError, match="Reviewed scope"):
        probe.verified_port(tmp_path)
    fresh_approval = base | {
        "scope": probe.STOP_SCOPE,
        "operator_mode": probe.STOP_MODE,
        "approved": True,
    }
    (tmp_path / "approval.json").write_text(json.dumps(fresh_approval), encoding="utf-8")
    assert probe.verified_port(tmp_path) == ("COM3", digest, True)
