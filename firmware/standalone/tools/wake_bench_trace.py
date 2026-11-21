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


class WakeBenchTrace:
    """Keep the first and repeated WAIT evidence without serial operations."""

    def __init__(self):
        self._initial_nonce = None
        self._initial_reason = None
        self._repeated_reason = None
        self._repeated_nonce_changed = None
        self._checkpoints = []

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

    def complete(self):
        return (
            self._initial_reason is not None
            and self._repeated_nonce_changed is None
            and tuple(self._checkpoints) in _COMPLETE
        )

    def summary(self):
        return {
            "initial_reset_reason": self._initial_reason,
            "repeated_reset_reason": self._repeated_reason,
            "repeated_nonce_changed": self._repeated_nonce_changed,
            "wake_checkpoints": self._checkpoints.copy(),
        }
