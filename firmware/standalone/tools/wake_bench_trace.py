"""Allowlisted evidence from the silent ESP32-S3 wake diagnostic."""

import re

_PREFIX = (
    "model_reset_begin",
    "model_reset_return",
    "input_allocate_begin",
    "input_allocated",
    "input_configured",
    "first_poll_begin",
)
_POLL_RETURN = ("first_poll_return",)
_DETECT = ("first_detect_begin", "first_detect_return")
_FINAL_RESET = ("final_model_reset_begin", "final_model_reset_return")
_COMPLETE = (
    _PREFIX + _POLL_RETURN + _DETECT + _FINAL_RESET,
    _PREFIX + _DETECT + _POLL_RETURN + _FINAL_RESET,
)
_CHECKPOINTS = frozenset(_COMPLETE[0])
_HEAP_WINDOW = "MODEL_RESIDENT_LOCAL_TLS_WIRE"
_HEAP_NUMBERS = frozenset(
    {"internal_free_at_start", "internal_min", "psram_free_at_start", "psram_min"}
)
_HEAP_FIELDS = _HEAP_NUMBERS | {"heap_window", "operating_admission"}
_MIC_CLEAN = frozenset({"detected", "not_detected"})
_MIC_RESULTS = _MIC_CLEAN | {"denied", "stopped", "fault", "memory_denied"}
_MIC_FIELDS = frozenset({"mic_wake_trial", "result", "operating_admission"})
_MIC_COUNT_FIELDS = frozenset({"frames_read", "all_zero_frames", "full_scale_samples"})
_MIC_DIAGNOSTIC_FIELDS = frozenset({"stage", "codec_cleanup_unverified"})
_MIC_CLOCK_REASONS = frozenset(
    {
        "invalid_start",
        "clock_rollback",
        "poll_gap_exceeded",
        "poll_duration_exceeded",
        "capture_window_exceeded",
    }
)
_MIC_DEADLINE_FIELDS = frozenset(
    {"frames_read", "model_calls", "last_model_result", "last_poll_step"}
)
_MIC_MODEL_RESULTS = frozenset({"not_called", "none", "detected", "error"})
_MIC_POLL_STEPS = frozenset({"poll_entry", "mic_read", "input_processing", "model_return"})
_MIC_MEMORY_STAGES = frozenset({"baseline_memory", "resident_memory"})
_MIC_FAULT_STAGES = frozenset(
    {
        "model_prepare",
        "input_format",
        "model_reset",
        "i2c_bus",
        "board_power",
        "amplifier_reset",
        "board_release",
        "i2s_rx",
        "codec_prepare",
        "codec_open",
        "capture_clock",
        "capture_read",
        "wake_input",
        "codec_release",
    }
)
_MIC_STOP_STAGES = _MIC_FAULT_STAGES | _MIC_MEMORY_STAGES | {"admission"}
_MIC_RESULT_STAGES = {
    "detected": frozenset({"complete"}),
    "not_detected": frozenset({"complete"}),
    "denied": frozenset({"admission"}),
    "stopped": _MIC_STOP_STAGES,
    "memory_denied": _MIC_MEMORY_STAGES,
    "fault": _MIC_FAULT_STAGES,
}


def _valid_deadline_progress(progress: object) -> bool:
    if not isinstance(progress, dict) or set(progress) != _MIC_DEADLINE_FIELDS:
        return False
    frames = progress["frames_read"]
    calls = progress["model_calls"]
    result = progress["last_model_result"]
    step = progress["last_poll_step"]
    return (
        type(frames) is int
        and type(calls) is int
        and 0 <= calls <= frames <= 500
        and isinstance(result, str)
        and result in _MIC_MODEL_RESULTS
        and isinstance(step, str)
        and step in _MIC_POLL_STEPS
        and (calls == 0) == (result == "not_called")
        and (step != "model_return" or calls > 0)
        and (result not in {"detected", "error"} or step == "model_return")
    )


def parse_mic_wake_trial_report(record: object) -> dict:
    """Validate the fixed per-trial record emitted by the microphone diagnostic."""
    if (
        not isinstance(record, dict)
        or record.get("mic_wake_trial")
        not in ("MIC_WAKE_TRIAL_V1", "MIC_WAKE_TRIAL_V2", "MIC_WAKE_TRIAL_V3", "MIC_WAKE_TRIAL_V4")
        or record.get("operating_admission") is not False
        or not isinstance(record.get("result"), str)
        or record["result"] not in _MIC_RESULTS
    ):
        raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
    clean = record["result"] in _MIC_CLEAN
    fields = _MIC_FIELDS | _MIC_COUNT_FIELDS if clean else _MIC_FIELDS
    version = record["mic_wake_trial"]
    has_diagnostic = version != "MIC_WAKE_TRIAL_V1"
    has_clock_reason = (
        version in ("MIC_WAKE_TRIAL_V3", "MIC_WAKE_TRIAL_V4")
        and record.get("stage") == "capture_clock"
    )
    has_deadline_progress = (
        version == "MIC_WAKE_TRIAL_V4"
        and has_clock_reason
        and record.get("clock_reason") == "capture_window_exceeded"
    )
    if has_diagnostic:
        fields |= _MIC_DIAGNOSTIC_FIELDS
    if has_clock_reason:
        fields |= {"clock_reason"}
    if has_deadline_progress:
        fields |= {"deadline_progress"}
    if set(record) != fields:
        raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
    if has_diagnostic:
        result = record["result"]
        stage, cleanup = record["stage"], record["codec_cleanup_unverified"]
        if (
            not isinstance(stage, str)
            or stage not in _MIC_RESULT_STAGES[result]
            or type(cleanup) is not bool
            or (cleanup and result != "fault")
            or (cleanup and stage in ("model_prepare", "model_reset"))
            or (result == "fault" and stage == "codec_release" and not cleanup)
        ):
            raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
    if has_clock_reason:
        reason = record["clock_reason"]
        if (
            record["result"] != "fault"
            or not isinstance(reason, str)
            or reason not in _MIC_CLOCK_REASONS
        ):
            raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
    if clean:
        frames, zeroes, full_scale = (
            record["frames_read"],
            record["all_zero_frames"],
            record["full_scale_samples"],
        )
        if (
            any(type(value) is not int for value in (frames, zeroes, full_scale))
            or not 1 <= frames <= 500
            or not 0 <= zeroes <= frames
            or not 0 <= full_scale <= (frames - zeroes) * 240
        ):
            raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
    if has_deadline_progress:
        progress = record["deadline_progress"]
        if not _valid_deadline_progress(progress):
            raise ValueError("INVALID_MIC_WAKE_TRIAL_REPORT")
        return record | {"deadline_progress": progress.copy()}
    return record.copy()


class WakeBenchTrace:
    """Keep fixed diagnostic evidence without serial operations."""

    def __init__(self):
        self._initial_nonce = None
        self._initial_reason = None
        self._repeated_reason = None
        self._repeated_nonce_changed = None
        self._checkpoints = []
        self._heap_window = None

    def observe_wait(self, record):
        nonce = record.get("nonce")
        if (
            record.get("bench") != "WAIT_LOCAL_START"
            or not isinstance(nonce, str)
            or re.fullmatch(r"[0-9A-F]{8}", nonce) is None
            or nonce == "00000000"
            or record.get("wait_ms") != 60000
        ):
            raise ValueError("INVALID_LOCAL_CHALLENGE")

        # ESP-IDF 6.1 enum pinned by the target build's static_assert.
        reason = record.get("reset_reason")
        if type(reason) is not int or not 0 <= reason <= 15:
            reason = None
        if self._initial_nonce is None:
            self._initial_nonce = nonce
            self._initial_reason = reason
            return False
        self._repeated_reason = reason
        self._repeated_nonce_changed = nonce != self._initial_nonce
        return True

    def observe_checkpoint(self, record):
        name = record.get("wake_checkpoint")
        if (
            self._initial_nonce is None
            or self._repeated_nonce_changed is not None
            or not isinstance(name, str)
            or name not in _CHECKPOINTS
            or record.get("operating_admission") is not False
        ):
            return False
        if name in self._checkpoints:
            raise ValueError("DUPLICATE_WAKE_CHECKPOINT")
        self._checkpoints.append(name)
        return True

    def observe_heap_window(self, record):
        if (
            self._initial_nonce is None
            or self._repeated_nonce_changed is not None
            or self._checkpoints
            or not isinstance(record, dict)
            or set(record) != _HEAP_FIELDS
            or record["heap_window"] != _HEAP_WINDOW
            or record["operating_admission"] is not False
        ):
            return False
        numbers = {field: record[field] for field in _HEAP_NUMBERS}
        if any(type(value) is not int or not 0 <= value < 2**32 for value in numbers.values()):
            return False
        for pool in ("internal", "psram"):
            baseline, minimum = numbers[f"{pool}_free_at_start"], numbers[f"{pool}_min"]
            if not 0 <= minimum <= baseline or baseline == 0:
                return False
            numbers[f"{pool}_watermark_drop"] = baseline - minimum
        if self._heap_window is not None:
            raise ValueError("DUPLICATE_HEAP_WINDOW")
        self._heap_window = numbers
        return True

    def complete(self):
        return (
            self._initial_reason is not None
            and self._repeated_nonce_changed is None
            and tuple(self._checkpoints) in _COMPLETE
        )

    def summary(self):
        result = {
            "initial_reset_reason": self._initial_reason,
            "repeated_reset_reason": self._repeated_reason,
            "repeated_nonce_changed": self._repeated_nonce_changed,
            "wake_checkpoints": self._checkpoints.copy(),
        }
        if self._heap_window is not None:
            result["model_resident_local_tls_wire"] = self._heap_window.copy()
        return result
