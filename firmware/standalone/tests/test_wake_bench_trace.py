"""Allowlisted reset evidence without serial I/O or audio."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from wake_bench_trace import WakeBenchTrace  # noqa: E402


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
