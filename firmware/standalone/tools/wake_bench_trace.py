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
