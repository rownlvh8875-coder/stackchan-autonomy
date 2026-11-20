"""Regression tests for descriptive, untrusted cross-file K151 bench reports."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def review(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    tool_dir = root / "tools"
    monkeypatch.syspath_prepend(str(tool_dir))
    spec = importlib.util.spec_from_file_location(
        "bench_campaign_review", tool_dir / "bench_campaign_review.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample(stop_us=600, drain_us=1200):
    stop_start = 1000
    tx_start = 2000
    return {
        "schema": "k151-audio-bench-v1",
        "clock": "shared-instrument-monotonic-us",
        "trials": [
            {
                "id": "stop-01",
                "kind": "stop_mute",
                "events": [
                    {"name": "physical_stop_edge", "source": "stop_scope", "t_us": stop_start},
                    {
                        "name": "amplifier_electrically_muted",
                        "source": "amp_scope",
                        "t_us": stop_start + stop_us,
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
                        "t_us": tx_start,
                    },
                    {
                        "name": "tx_dma_empty",
                        "source": "dma_observer",
                        "t_us": tx_start + 300,
                    },
                    {
                        "name": "codec_output_idle",
                        "source": "codec_observer",
                        "t_us": tx_start + 800,
                    },
                    {
                        "name": "amplifier_electrically_muted",
                        "source": "amp_scope",
                        "t_us": tx_start + drain_us,
                    },
                ],
            },
        ],
    }


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def test_cross_file_stats_not_certification(review):
    raw = [encoded(sample(600, 1200)), encoded(sample(800, 1600))]
    result = review.inspect_campaign(raw)
    assert result["status"] == "UNVERIFIED_MULTI_TRACE_SUMMARY"
    assert result["input_file_count"] == 2
    assert result["distributions"]["stop_mute"]["files_with_kind"] == 2
    assert result["distributions"]["stop_mute"]["descriptive_metrics"][
        "stop_to_electrical_mute_us"
    ] == {
        "count": 2,
        "minimum_us": 600,
        "median_us": 700.0,
        "maximum_us": 800,
        "span_us": 200,
    }
    assert (
        result["distributions"]["tx_drain"]["descriptive_metrics"]["last_write_to_amp_mute_us"][
            "span_us"
        ]
        == 400
    )
    assert len(result["input_files"][0]["sha256"]) == 64
    assert not result["raw_measurement_provenance_verified"]
    assert not result["cross_file_clock_sync_verified"]
    assert not result["repeatability_proven"]
    assert not result["electrical_safety_proven"]
    assert not result["install_authorized"]
    assert not result["device_accessed"]


@pytest.mark.parametrize(
    ("files", "error"),
    [
        ([encoded(sample())], "invalid_file_count"),
        ([encoded(sample())] * 2, "duplicate_input_content"),
        (
            [
                encoded(sample()),
                encoded({"schema": "k151-audio-bench-v1", "clock": "broken", "trials": []}),
            ],
            "rejected_input_trace",
        ),
        ([encoded(sample()), b"{not-json"], "rejected_input_trace"),
        (
            [
                encoded(
                    {
                        "schema": "k151-audio-bench-v1",
                        "clock": "shared-instrument-monotonic-us",
                        "trials": [sample()["trials"][0]],
                    }
                ),
                encoded(
                    {
                        "schema": "k151-audio-bench-v1",
                        "clock": "shared-instrument-monotonic-us",
                        "trials": [sample()["trials"][1]],
                    }
                ),
            ],
            "insufficient_cross_file_coverage",
        ),
    ],
)
def test_rejects_incomplete_and_duplicate_campaigns(review, files, error):
    with pytest.raises(review.CampaignRejected, match=error):
        review.inspect_campaign(files)


def test_oversize_and_private_path_not_echoed(tmp_path, review):
    first = tmp_path / "PRIVATE-file-one.json"
    second = tmp_path / "PRIVATE-file-two.json"
    first_raw = encoded(sample(600, 1200))
    second_raw = encoded(sample(801, 1600))
    first.write_bytes(first_raw)
    second.write_bytes(second_raw)
    cmd = [sys.executable, str(Path(review.__file__)), str(first), str(second)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
    assert done.returncode == 0
    result = json.loads(done.stdout)
    assert result["status"] == "UNVERIFIED_MULTI_TRACE_SUMMARY"
    assert "PRIVATE-" not in done.stdout
    assert first.read_bytes() == first_raw and second.read_bytes() == second_raw

    second.write_bytes(b"x" * (review.MAX_INPUT_BYTES + 1))
    rejected = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["error"] == "rejected_input_trace"
    assert "PRIVATE-" not in rejected.stdout


def test_cross_file_comparability_never_inferred(review):
    a = sample(600, 1200)
    b = copy.deepcopy(a)
    # Identical timing profiles with different raw bytes still do not prove
    # independent measurements or calibrated clocks.
    b["trials"][0]["id"] = "stop-02"
    result = review.inspect_campaign([encoded(a), encoded(b)])
    assert (
        result["distributions"]["stop_mute"]["descriptive_metrics"]["stop_to_electrical_mute_us"][
            "span_us"
        ]
        == 0
    )
    assert not result["repeatability_proven"]
