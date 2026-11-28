"""Allowlisted reset evidence without serial I/O or audio."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from wake_bench_trace import WakeBenchTrace, parse_mic_wake_trial_report  # noqa: E402


def waiting(nonce, reason):
    return {
        "bench": "WAIT_LOCAL_START",
        "nonce": nonce,
        "wait_ms": 60000,
        "reset_reason": reason,
    }


def checkpoint(name):
    return {"wake_checkpoint": name, "operating_admission": False}


def test_repeated_wait_preserves_reset_reason_before_abort_without_nonce():
    trace = WakeBenchTrace()
    assert not trace.observe_wait(waiting("1A1A1A1A", 1))
    trace.observe_checkpoint(checkpoint("model_reset_begin"))
    assert trace.observe_wait(waiting("2B2B2B2B", 4))
    assert trace.summary() == {
        "initial_reset_reason": 1,
        "repeated_reset_reason": 4,
        "repeated_nonce_changed": True,
        "wake_checkpoints": ["model_reset_begin"],
    }
    assert "1A1A1A1A" not in json.dumps(trace.summary())
    assert "2B2B2B2B" not in json.dumps(trace.summary())
    assert not trace.complete()


def test_duplicate_and_invalid_reason_cannot_be_claimed_as_new_boot():
    trace = WakeBenchTrace()
    assert not trace.observe_wait(waiting("AABBCCDD", None))
    assert trace.observe_wait(waiting("AABBCCDD", True))
    assert trace.summary()["repeated_nonce_changed"] is False
    assert trace.summary()["repeated_reset_reason"] is None


def test_invalid_wait_is_rejected():
    trace = WakeBenchTrace()
    with pytest.raises(ValueError, match="INVALID_LOCAL_CHALLENGE"):
        trace.observe_wait(waiting("00000000", 9))
    assert not trace.observe_wait(waiting("01AB01AB", 15))


@pytest.mark.parametrize("detect_in_first_poll", [False, True])
def test_terminal_evidence_requires_all_checkpoints_in_order(detect_in_first_poll):
    trace = WakeBenchTrace()
    trace.observe_wait(waiting("AABBCCDD", 0))
    initial = [
        "model_reset_begin",
        "model_reset_return",
        "input_allocate_begin",
        "input_allocated",
        "input_configured",
        "first_poll_begin",
    ]
    detect = ["first_detect_begin", "first_detect_return"]
    middle = (
        detect + ["first_poll_return"] if detect_in_first_poll else ["first_poll_return"] + detect
    )
    for name in initial + middle + ["final_model_reset_begin"]:
        assert trace.observe_checkpoint(checkpoint(name))
    assert not trace.complete()
    assert trace.observe_checkpoint(checkpoint("final_model_reset_return"))
    assert trace.complete()
    assert trace.observe_wait(waiting("02020002", 9))
    assert not trace.complete()


def test_only_fixed_inactive_checkpoint_values_are_retained():
    trace = WakeBenchTrace()
    assert not trace.observe_checkpoint(checkpoint("model_reset_begin"))
    trace.observe_wait(waiting("AABBCCDD", 1))
    for value in (
        checkpoint("private conversational text"),
        checkpoint(["model_reset_begin"]),
        {"wake_checkpoint": "model_reset_begin", "operating_admission": True},
    ):
        assert not trace.observe_checkpoint(value)
    assert trace.observe_checkpoint(checkpoint("model_reset_begin"))
    with pytest.raises(ValueError, match="DUPLICATE_WAKE_CHECKPOINT"):
        trace.observe_checkpoint(checkpoint("model_reset_begin"))
    assert trace.summary()["wake_checkpoints"] == ["model_reset_begin"]


def heap_window():
    return {
        "heap_window": "MODEL_RESIDENT_LOCAL_TLS_WIRE",
        "internal_free_at_start": 355000,
        "internal_min": 290000,
        "psram_free_at_start": 8047000,
        "psram_min": 5712000,
        "operating_admission": False,
    }


def test_heap_window_records_only_the_post_model_baseline_and_loss():
    trace = WakeBenchTrace()
    assert not trace.observe_heap_window(heap_window())
    trace.observe_wait(waiting("AABBCCDD", 1))
    assert not trace.observe_heap_window([{}, "untrusted"])
    assert trace.observe_heap_window(heap_window())
    assert trace.summary()["model_resident_local_tls_wire"] == {
        "internal_free_at_start": 355000,
        "internal_min": 290000,
        "internal_watermark_drop": 65000,
        "psram_free_at_start": 8047000,
        "psram_min": 5712000,
        "psram_watermark_drop": 2335000,
    }
    with pytest.raises(ValueError, match="DUPLICATE_HEAP_WINDOW"):
        trace.observe_heap_window(heap_window())
    assert not trace.complete()


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "private text"},
        {"internal_min": True},
        {"internal_min": 355001},
        {"psram_free_at_start": 0},
        {"psram_min": -1},
        {"psram_free_at_start": 2**32},
        {"operating_admission": True},
        {"heap_window": "other_trial"},
    ],
)
def test_heap_window_rejects_non_numeric_inconsistent_or_unexpected_fields(change):
    trace = WakeBenchTrace()
    trace.observe_wait(waiting("AABBCCDD", 1))
    assert not trace.observe_heap_window(heap_window() | change)
    assert "model_resident_local_tls_wire" not in trace.summary()


@pytest.mark.parametrize("repeat_boot", [False, True])
def test_late_heap_window_is_rejected_after_wake_input_or_a_reset(repeat_boot):
    trace = WakeBenchTrace()
    trace.observe_wait(waiting("AABBCCDD", 1))
    if repeat_boot:
        trace.observe_wait(waiting("99BBCCDD", 4))
    else:
        trace.observe_checkpoint(checkpoint("model_reset_begin"))
    assert not trace.observe_heap_window(heap_window())


@pytest.mark.parametrize(
    "change",
    [
        {"raw_audio": "private text"},
        {"frames_read": 501},
        {"frames_read": 0},
        {"all_zero_frames": True},
        {"full_scale_samples": 721},
        {"result": "stopped"},
        {"result": "raw"},
        {"operating_admission": True},
    ],
)
def test_mic_wake_report_rejects_unexpected_or_impossible_values(change):
    record = {
        "mic_wake_trial": "MIC_WAKE_TRIAL_V1",
        "result": "detected",
        "operating_admission": False,
        "frames_read": 4,
        "all_zero_frames": 1,
        "full_scale_samples": 6,
    }
    assert parse_mic_wake_trial_report(record) == record
    with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
        parse_mic_wake_trial_report(record | change)


@pytest.mark.parametrize(
    "change",
    [
        {"stage": "arbitrary driver text"},
        {"stage": []},
        {"stage": "complete"},
        {"stage": "resident_memory"},
        {"stage": "model_prepare"},
        {"stage": "model_reset"},
        {"codec_cleanup_unverified": 1},
        {"result": "stopped"},
        {"stage": "codec_release", "codec_cleanup_unverified": False},
        {"frames_read": 1},
        {"raw_audio": "discard"},
    ],
)
def test_mic_wake_v2_rejects_unapproved_or_inconsistent_diagnostics(change):
    record = {
        "mic_wake_trial": "MIC_WAKE_TRIAL_V2",
        "result": "fault",
        "operating_admission": False,
        "stage": "capture_read",
        "codec_cleanup_unverified": True,
    }
    assert parse_mic_wake_trial_report(record) == record
    with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
        parse_mic_wake_trial_report(record | change)


CLOCK_FAULT_V3 = {
    "mic_wake_trial": "MIC_WAKE_TRIAL_V3",
    "result": "fault",
    "operating_admission": False,
    "stage": "capture_clock",
    "codec_cleanup_unverified": False,
    "clock_reason": "clock_rollback",
}


def test_mic_wake_clock_fault_requires_reason_in_v3_only():
    legacy = dict(CLOCK_FAULT_V3, mic_wake_trial="MIC_WAKE_TRIAL_V2")
    del legacy["clock_reason"]
    assert parse_mic_wake_trial_report(legacy) == legacy
    assert parse_mic_wake_trial_report(CLOCK_FAULT_V3) == CLOCK_FAULT_V3
    v4_clock_rollback = CLOCK_FAULT_V3 | {"mic_wake_trial": "MIC_WAKE_TRIAL_V4"}
    assert parse_mic_wake_trial_report(v4_clock_rollback) == v4_clock_rollback
    with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
        parse_mic_wake_trial_report(legacy | {"mic_wake_trial": "MIC_WAKE_TRIAL_V3"})


@pytest.mark.parametrize(
    "change",
    [
        {"mic_wake_trial": "MIC_WAKE_TRIAL_V2"},
        {"clock_reason": "untrusted driver output"},
        {"clock_reason": []},
        {"clock_reason": None},
        {"stage": "capture_read"},
        {"result": "stopped"},
        {"raw_audio": "discard"},
        {"frames_read": 1},
    ],
)
def test_mic_wake_v3_rejects_invalid_clock_diagnostics(change):
    with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
        parse_mic_wake_trial_report(CLOCK_FAULT_V3 | change)


DEADLINE_V4 = CLOCK_FAULT_V3 | {
    "mic_wake_trial": "MIC_WAKE_TRIAL_V4",
    "clock_reason": "capture_window_exceeded",
}
PROGRESS_V4 = {
    "frames_read": 500,
    "model_calls": 156,
    "last_model_result": "detected",
    "last_poll_step": "model_return",
}


def test_mic_wake_v4_requires_deadline_progress_only_for_window_overrun():
    record = DEADLINE_V4 | {"deadline_progress": PROGRESS_V4}
    assert parse_mic_wake_trial_report(record) == record
    for rejected in (
        DEADLINE_V4,
        record | {"clock_reason": "poll_duration_exceeded"},
        record | {"mic_wake_trial": "MIC_WAKE_TRIAL_V3"},
    ):
        with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
            parse_mic_wake_trial_report(rejected)


@pytest.mark.parametrize(
    "change",
    [
        {"frames_read": True},
        {"frames_read": 501},
        {"frames_read": 155},
        {"model_calls": 0},
        {"model_calls": -1},
        {"last_model_result": []},
        {"last_model_result": "not_called"},
        {"last_model_result": "raw"},
        {"last_poll_step": "mic_read"},
        {"last_poll_step": []},
        {"last_poll_step": "untrusted"},
        {"samples": [1]},
    ],
)
def test_mic_wake_v4_rejects_invalid_or_extra_progress_fields(change):
    record = DEADLINE_V4 | {"deadline_progress": PROGRESS_V4 | change}
    with pytest.raises(ValueError, match="INVALID_MIC_WAKE_TRIAL_REPORT"):
        parse_mic_wake_trial_report(record)
