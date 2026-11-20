"""Compare repeated K151 bench timing logs offline, without installation approval.

Reads only previously captured JSON traces. Mathematical consistency is not
measurement authenticity, clock synchronization, or electrical safety proof.
"""

import argparse
import json
import statistics
from pathlib import Path

from bench_trace_audit import MAX_INPUT_BYTES, RejectedTrace, audit_bytes

MIN_FILES = 2
MAX_FILES = 16
KINDS = ("stop_mute", "tx_drain")
METRICS = {
    "stop_mute": ("stop_to_electrical_mute_us",),
    "tx_drain": (
        "last_write_to_dma_empty_us",
        "last_write_to_codec_idle_us",
        "last_write_to_amp_mute_us",
    ),
}


class CampaignRejected(ValueError):
    """Fixed public error code, never include a file path or raw content."""


def inspect_campaign(sources: list[bytes]) -> dict:
    if not MIN_FILES <= len(sources) <= MAX_FILES:
        raise CampaignRejected("invalid_file_count")

    file_summaries = []
    all_metrics = {kind: {metric: [] for metric in METRICS[kind]} for kind in KINDS}
    file_coverage = {kind: set() for kind in KINDS}
    seen_hashes: set[str] = set()

    for index, raw in enumerate(sources):
        try:
            report = audit_bytes(raw)
        except RejectedTrace as exc:
            raise CampaignRejected("rejected_input_trace") from exc
        fingerprint = report["input_sha256"]
        if fingerprint in seen_hashes:
            raise CampaignRejected("duplicate_input_content")
        seen_hashes.add(fingerprint)

        counts = {kind: 0 for kind in KINDS}
        for trial in report["trial_summaries"]:
            kind = trial["kind"]
            counts[kind] += 1
            file_coverage[kind].add(index)
            for metric in METRICS[kind]:
                all_metrics[kind][metric].append(trial["derived"][metric])
        file_summaries.append({"sha256": fingerprint, "counts": counts})

    # Two files that each contain only one type do not establish repeatability
    # of the other type. Require independent files for EACH trial kind.
    if any(len(file_coverage[kind]) < 2 for kind in KINDS):
        raise CampaignRejected("insufficient_cross_file_coverage")

    distributions = {}
    for kind in KINDS:
        metrics = {}
        for name, samples in all_metrics[kind].items():
            if not samples:
                raise CampaignRejected("insufficient_metric_samples")
            sorted_samples = sorted(samples)
            metrics[name] = {
                "count": len(samples),
                "minimum_us": sorted_samples[0],
                "median_us": statistics.median(sorted_samples),
                "maximum_us": sorted_samples[-1],
                "span_us": sorted_samples[-1] - sorted_samples[0],
            }
        distributions[kind] = {
            "files_with_kind": len(file_coverage[kind]),
            "trial_count": len(all_metrics[kind][METRICS[kind][0]]),
            "descriptive_metrics": metrics,
        }

    return {
        "status": "UNVERIFIED_MULTI_TRACE_SUMMARY",
        "input_file_count": len(file_summaries),
        "input_files": file_summaries,
        "distributions": distributions,
        "only_structural_and_arithmetic_checks": True,
        "raw_measurement_provenance_verified": False,
        "cross_file_clock_sync_verified": False,
        "repeatability_proven": False,
        "electrical_safety_proven": False,
        "device_accessed": False,
        "install_authorized": False,
        "firmware_or_ota_modified": False,
        "explanation": (
            "Cross-file values are descriptive only. Two different file hashes "
            "are not proof of independent observations or calibrated clocks."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if not MIN_FILES <= len(args.traces) <= MAX_FILES:
            raise CampaignRejected("invalid_file_count")
        raw_inputs = []
        for path in args.traces:
            with path.open("rb") as file:
                raw_inputs.append(file.read(MAX_INPUT_BYTES + 1))
        result = inspect_campaign(raw_inputs)
        exit_code = 0
    except (OSError, CampaignRejected) as exc:
        result = {
            "status": "REJECTED_BENCH_CAMPAIGN",
            "error": exc.args[0] if isinstance(exc, CampaignRejected) else "input_unavailable",
            "device_accessed": False,
            "install_authorized": False,
        }
        exit_code = 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
