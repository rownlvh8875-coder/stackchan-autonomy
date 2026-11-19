"""Offline-only K151 bench log schema and timestamp regression tests."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def auditor():
    path = Path(__file__).resolve().parents[1] / "tools" / "bench_trace_audit.py"
    spec = importlib.util.spec_from_file_location("bench_trace_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example():
    return {
        "schema": "k151-audio-bench-v1",
        "clock": "shared-instrument-monotonic-us",
        "trials": [
            {
                "id": "stop-01",
                "kind": "stop_mute",
                "events": [
                    {"name": "physical_stop_edge", "source": "stop_scope", "t_us": 1000},
                    {
                        "name": "amplifier_electrically_muted",
                        "source": "amp_scope",
                        "t_us": 1600,
                    },
                ],
            },
            {
                "id": "drain-01",
                "kind": "tx_drain",
                "events": [
                    {
                        "name": "last_pcm_write_accepted",
                        "source": "codec_write_trace",
                        "t_us": 2000,
                    },
                    {"name": "tx_dma_empty", "source": "dma_observer", "t_us": 2600},
                    {
                        "name": "codec_output_idle",
                        "source": "codec_observer",
                        "t_us": 3000,
                    },
                    {
                        "name": "amplifier_electrically_muted",
                        "source": "amp_scope",
                        "t_us": 3200,
                    },
                ],
            },
        ],
    }


def test_unverified_summary_never_grants_approval(auditor, example):
    raw = json.dumps(example, ensure_ascii=False).encode()
    report = auditor.audit_bytes(raw)
    assert report["trial_count"] == 2
    assert report["trial_summaries"][0]["derived"] == {"stop_to_electrical_mute_us": 600}
    assert report["trial_summaries"][1]["derived"] == {
        "last_write_to_dma_empty_us": 600,
        "last_write_to_codec_idle_us": 1000,
        "last_write_to_amp_mute_us": 1200,
    }
    assert len(report["input_sha256"]) == 64
    assert not report["source_authenticity_verified"]
    assert not report["common_clock_proven"]
    assert not report["electrical_safety_proven"]
    assert not report["install_authorized"]
    assert not report["physical_hardware_accessed"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda x: x.update({"schema": "fake"}), "unsupported_schema_or_clock"),
        (lambda x: x.update({"clock": "system_clock"}), "unsupported_schema_or_clock"),
        (lambda x: x.update({"extra": 1}), "invalid_fields"),
        (lambda x: x.update({"trials": []}), "invalid_trial_count"),
        (
            lambda x: x["trials"][1].update({"id": "stop-01"}),
            "duplicate_trial_id",
        ),
        (lambda x: x["trials"][0].update({"id": "../outside"}), "invalid_trial_id"),
        (lambda x: x["trials"][0].update({"kind": "flashing"}), "invalid_trial_kind"),
        (lambda x: x["trials"][0]["events"].pop(), "missing_or_extra_events"),
        (
            lambda x: x["trials"][0]["events"][0].update({"source": "fake"}),
            "event_order_or_witness_mismatch",
        ),
        (
            lambda x: x["trials"][0]["events"][0].update({"t_us": True}),
            "invalid_timestamp",
        ),
        (
            lambda x: x["trials"][0]["events"][1].update({"t_us": 1000}),
            "non_monotonic_event_times",
        ),
        (
            lambda x: x["trials"][1]["events"][1].update({"t_us": 5000}),
            "non_monotonic_event_times",
        ),
    ],
)
def test_bad_trace_fails_closed(auditor, example, mutation, expected):
    candidate = copy.deepcopy(example)
    mutation(candidate)
    with pytest.raises(auditor.RejectedTrace, match=expected):
        auditor.inspect_trace(candidate)


def test_input_limits_json_rejection_and_does_not_echo(auditor, example):
    with pytest.raises(auditor.RejectedTrace, match="invalid_input_size"):
        auditor.audit_bytes(b"x" * (auditor.MAX_INPUT_BYTES + 1))
    with pytest.raises(auditor.RejectedTrace, match="invalid_json_or_encoding"):
        auditor.audit_bytes(b"{bad json")
    with pytest.raises(auditor.RejectedTrace, match="invalid_json_or_encoding"):
        auditor.audit_bytes(b"\xff")
    assert not auditor.inspect_trace(example)["install_authorized"]
    with pytest.raises(auditor.RejectedTrace, match="duplicate_json_key"):
        auditor.audit_bytes(b'{"schema":"one","schema":"two"}')


def test_offline_cli_parses_without_modifying_input(tmp_path, auditor, example):
    source = tmp_path / "input.json"
    raw = json.dumps(example).encode()
    source.write_bytes(raw)
    tool = Path(auditor.__file__)
    run = subprocess.run(
        [sys.executable, str(tool), str(source)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert run.returncode == 0
    assert not json.loads(run.stdout)["install_authorized"]
    assert source.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [source]

    source.write_text('{"schema":"k151-audio-bench-v1","trials":[]}')
    denied = subprocess.run(
        [sys.executable, str(tool), str(source)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert denied.returncode == 2
    assert json.loads(denied.stdout)["status"] == "REJECTED_BENCH_LOG"
