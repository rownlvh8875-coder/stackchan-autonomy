"""Validate offline K151 bench timing logs; never authorize hardware activity.

This tool only audits the structure and internal consistency of data supplied
by an operator. It cannot authenticate instruments, measurements, clocks, or
the provenance of supplied log entries. No device or network access.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "k151-audio-bench-v1"
CLOCK = "shared-instrument-monotonic-us"
MAX_INPUT_BYTES = 131_072
MAX_TRIALS = 100
EVENTS = {
    "stop_mute": (
        ("physical_stop_edge", "stop_scope"),
        ("amplifier_electrically_muted", "amp_scope"),
    ),
    "tx_drain": (
        ("last_pcm_write_accepted", "codec_write_trace"),
        ("tx_dma_empty", "dma_observer"),
        ("codec_output_idle", "codec_observer"),
        ("amplifier_electrically_muted", "amp_scope"),
    ),
}
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")


class RejectedTrace(ValueError):
    """Public fixed error code; never include private input in responses."""


def _expect_keys(obj: object, keys: set[str]) -> dict:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise RejectedTrace("invalid_fields")
    return obj


def _unique_json_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RejectedTrace("duplicate_json_key")
        result[key] = value
    return result


def _timestamp(value: object) -> int:
    if type(value) is not int or value < 0 or value > 9_000_000_000_000_000:
        raise RejectedTrace("invalid_timestamp")
    return value


def inspect_trace(payload: object) -> dict:
    data = _expect_keys(payload, {"schema", "clock", "trials"})
    if data["schema"] != SCHEMA or data["clock"] != CLOCK:
        raise RejectedTrace("unsupported_schema_or_clock")
    trials = data["trials"]
    if not isinstance(trials, list) or not 1 <= len(trials) <= MAX_TRIALS:
        raise RejectedTrace("invalid_trial_count")
    summaries = []
    seen_ids: set[str] = set()
    for trial in trials:
        trial = _expect_keys(trial, {"id", "kind", "events"})
        identifier = trial["id"]
        kind = trial["kind"]
        if not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier):
            raise RejectedTrace("invalid_trial_id")
        if identifier in seen_ids:
            raise RejectedTrace("duplicate_trial_id")
        seen_ids.add(identifier)
        if not isinstance(kind, str) or kind not in EVENTS:
            raise RejectedTrace("invalid_trial_kind")
        expected = EVENTS[kind]
        events = trial["events"]
        if not isinstance(events, list) or len(events) != len(expected):
            raise RejectedTrace("missing_or_extra_events")

        times = {}
        for actual, (name, witness) in zip(events, expected, strict=True):
            event = _expect_keys(actual, {"name", "source", "t_us"})
            if event["name"] != name or event["source"] != witness:
                raise RejectedTrace("event_order_or_witness_mismatch")
            times[name] = _timestamp(event["t_us"])

        ordered = [times[name] for name, _ in expected]
        if not all(later > earlier for earlier, later in zip(ordered, ordered[1:])):
            raise RejectedTrace("non_monotonic_event_times")

        if kind == "stop_mute":
            deltas = {
                "stop_to_electrical_mute_us": (
                    times["amplifier_electrically_muted"] - times["physical_stop_edge"]
                )
            }
        else:
            deltas = {
                "last_write_to_dma_empty_us": (
                    times["tx_dma_empty"] - times["last_pcm_write_accepted"]
                ),
                "last_write_to_codec_idle_us": (
                    times["codec_output_idle"] - times["last_pcm_write_accepted"]
                ),
                "last_write_to_amp_mute_us": (
                    times["amplifier_electrically_muted"] - times["last_pcm_write_accepted"]
                ),
            }
        summaries.append({"id": identifier, "kind": kind, "derived": deltas})

    return {
        "status": "UNVERIFIED_OPERATOR_SUPPLIED_TRACE",
        "source_authenticity_verified": False,
        "common_clock_proven": False,
        "electrical_safety_proven": False,
        "physical_hardware_accessed": False,
        "install_authorized": False,
        "flash_or_ota_modified": False,
        "trial_count": len(summaries),
        "trial_summaries": summaries,
        "explanation": (
            "Only event order and arithmetic were checked. "
            "Supplied witness names and timestamps are untrusted labels."
        ),
    }


def audit_bytes(raw: bytes) -> dict:
    if len(raw) == 0 or len(raw) > MAX_INPUT_BYTES:
        raise RejectedTrace("invalid_input_size")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_fields)
    except RejectedTrace:
        raise
    except (ValueError, UnicodeError) as exc:
        raise RejectedTrace("invalid_json_or_encoding") from exc
    result = inspect_trace(payload)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="previously captured offline JSON")
    args = parser.parse_args(argv)
    try:
        with args.trace.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        result = audit_bytes(raw)
        exit_code = 0
    except (OSError, RejectedTrace) as exc:
        result = {
            "status": "REJECTED_BENCH_LOG",
            "error": exc.args[0] if isinstance(exc, RejectedTrace) else "input_unavailable",
            "install_authorized": False,
            "physical_hardware_accessed": False,
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
