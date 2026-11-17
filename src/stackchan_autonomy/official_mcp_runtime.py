"""Sequential, cancellable recovery of complete MCP sessions, never tool calls."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from .official_mcp_errors import BridgeError


async def run_reconnecting(
    session: Callable[[Callable[[str], None]], Awaitable[None]],
    *,
    emit: Callable[[str], None],
    sleep=asyncio.sleep,
    clock=time.monotonic,
) -> None:
    delay, reconnects = 2, 0

    def report(line):
        try:
            emit(line)
        except Exception:
            raise BridgeError("OFFICIAL_MCP_OUTPUT_FAILED") from None

    while True:
        ready_at = None

        def session_report(line):
            nonlocal ready_at
            if line == "OFFICIAL_MCP_INITIALIZED" and ready_at is None:
                ready_at = clock()
            report(line)

        try:
            # All per-session SDK/HTTP/storage lifetimes unwind inside this await.
            await session(session_report)
            return
        except BridgeError as error:
            if not error.retryable:
                raise
            report(error.code)
        if ready_at is not None and clock() - ready_at >= 60:
            delay = 2
        report(f"OFFICIAL_MCP_RECONNECT_WAIT={delay}")
        await sleep(delay)
        reconnects += 1
        report(f"OFFICIAL_MCP_RECONNECTING={reconnects}")
        delay = min(60, delay * 2)
