"""Fixed public errors and conservative transport recovery classification."""

import ssl

from websockets.exceptions import (
    ConnectionClosed,
    InvalidMessage,
    InvalidProxyMessage,
    InvalidProxyStatus,
    InvalidStatus,
)

_TEMPORARY = frozenset(
    {
        "OFFICIAL_MCP_CONNECTION_FAILED",
        "OFFICIAL_MCP_REMOTE_CLOSED",
        "OFFICIAL_MCP_INITIALIZATION_TIMEOUT",
    }
)
_CODES = _TEMPORARY | frozenset(
    {
        "OFFICIAL_MCP_INVALID_ENDPOINT",
        "OFFICIAL_MCP_PROTOCOL_FAILED",
        "OFFICIAL_MCP_OUTPUT_FAILED",
        "OFFICIAL_MCP_REDIRECT_REJECTED",
        "OFFICIAL_MCP_AUTH_FAILED",
        "OFFICIAL_MCP_TLS_FAILED",
        "OFFICIAL_MCP_HANDSHAKE_FAILED",
        "OFFICIAL_MCP_RATE_LIMITED",
        "OFFICIAL_MCP_REMOTE_REJECTED",
        "PC_TOOL_UNSUPPORTED",
        "PC_SOAK_REPORT_UNAVAILABLE",
        "PC_GPT_CONFIG_REQUIRED",
        "PC_GPT_INVALID_QUESTION",
        "PC_GPT_BUDGET_EXHAUSTED",
        "PC_GPT_STORAGE_UNAVAILABLE",
        "PC_GPT_UNAVAILABLE",
        "PC_OBSERVER_UNAVAILABLE",
        "PC_OBSERVER_PROTOCOL_FAILED",
        "PC_OBSERVER_PAIRING_REQUIRED",
        "PC_OBSERVER_IDENTITY_CHANGED",
        "PC_OBSERVER_BUSY",
        "PC_OBSERVER_CONSENT_REQUIRED",
        "PC_OBSERVER_CANCELLED",
    }
)


class BridgeError(Exception):
    """Public messages contain fixed codes, never transport details or close reasons."""

    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code if code in _CODES else "OFFICIAL_MCP_CONNECTION_FAILED"
        self.retryable = bool(retryable and code in _TEMPORARY)
        super().__init__(self.code)


def classify_failure(error: Exception) -> BridgeError:
    if isinstance(error, BridgeError):
        return error
    if isinstance(error, ExceptionGroup):
        failures = [classify_failure(child) for child in error.exceptions]
        return next((failure for failure in failures if not failure.retryable), failures[0])
    if isinstance(error, ConnectionClosed):
        close = error.rcvd or error.sent
        code = close.code if close is not None else 1006
        if code in {1000, 1001, 1005, 1006, 1011, 1012, 1013}:
            return BridgeError("OFFICIAL_MCP_REMOTE_CLOSED", retryable=True)
        return BridgeError("OFFICIAL_MCP_REMOTE_REJECTED")
    if isinstance(error, (InvalidStatus, InvalidProxyStatus)):
        status = error.response.status_code
        if status in {401, 403, 407}:
            return BridgeError("OFFICIAL_MCP_AUTH_FAILED")
        if status == 429:
            return BridgeError("OFFICIAL_MCP_RATE_LIMITED")
        if 500 <= status <= 599:
            return BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)
        return BridgeError("OFFICIAL_MCP_HANDSHAKE_FAILED")
    if isinstance(error, ssl.SSLError):
        return BridgeError("OFFICIAL_MCP_TLS_FAILED")
    if isinstance(error, (InvalidMessage, InvalidProxyMessage)) and isinstance(
        error.__cause__, EOFError
    ):
        # websockets wraps an interrupted upgrade/CONNECT response this way.
        # Other malformed HTTP responses remain fatal.
        return BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)
    if isinstance(error, (OSError, TimeoutError)):
        return BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)
    return BridgeError("OFFICIAL_MCP_CONNECTION_FAILED")
