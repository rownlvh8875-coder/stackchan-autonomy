"""Recovery contracts with real local WebSockets; no device or paid network calls."""

import asyncio
import importlib
import ssl
from contextlib import asynccontextmanager

import pytest
from test_official_mcp import ENDPOINT, bridge_module, initialize, request
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from stackchan_autonomy.official_mcp import BridgeError, run_bridge


def runtime():
    return importlib.import_module("stackchan_autonomy.official_mcp_runtime")


@pytest.mark.parametrize(
    "failure,code,retryable",
    [
        (OSError("synthetic-private"), "OFFICIAL_MCP_CONNECTION_FAILED", True),
        (TimeoutError("synthetic-private"), "OFFICIAL_MCP_CONNECTION_FAILED", True),
        (ssl.SSLCertVerificationError("synthetic-private"), "OFFICIAL_MCP_TLS_FAILED", False),
        (
            InvalidStatus(Response(401, "private", Headers(), b"private")),
            "OFFICIAL_MCP_AUTH_FAILED",
            False,
        ),
        (
            InvalidStatus(Response(403, "private", Headers(), b"private")),
            "OFFICIAL_MCP_AUTH_FAILED",
            False,
        ),
        (
            InvalidStatus(Response(404, "private", Headers(), b"private")),
            "OFFICIAL_MCP_HANDSHAKE_FAILED",
            False,
        ),
        (
            InvalidStatus(Response(429, "private", Headers({"Retry-After": "120"}), b"private")),
            "OFFICIAL_MCP_RATE_LIMITED",
            False,
        ),
        (
            InvalidStatus(Response(503, "private", Headers(), b"private")),
            "OFFICIAL_MCP_CONNECTION_FAILED",
            True,
        ),
        (RuntimeError("synthetic-private"), "OFFICIAL_MCP_CONNECTION_FAILED", False),
        (
            ExceptionGroup(
                "private", [OSError("private"), BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")]
            ),
            "OFFICIAL_MCP_PROTOCOL_FAILED",
            False,
        ),
    ],
)
async def test_real_transport_boundary_classifies_failures_without_echo(
    monkeypatch, failure, code, retryable
):
    module = bridge_module()

    def failed_dial(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module, "connect", failed_dial)
    lines = []
    with pytest.raises(BridgeError) as caught:
        await run_bridge(ENDPOINT, emit=lines.append)
    assert caught.value.code == code and caught.value.retryable is retryable
    assert "private" not in str(caught.value) + repr(caught.value) + str(lines)


async def test_capped_backoff_and_no_overlap_or_replay():
    waits, events = [], []
    attempts = 0

    async def session(emit):
        nonlocal attempts
        attempts += 1
        events.append(("open", attempts))
        try:
            if attempts <= 8:
                raise BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)
        finally:
            events.append(("close", attempts))

    async def sleep(seconds):
        assert events[-1] == ("close", attempts)
        waits.append(seconds)

    await runtime().run_reconnecting(session, emit=lambda s: None, sleep=sleep)
    assert waits == [2, 4, 8, 16, 32, 60, 60, 60]
    assert attempts == 9
    assert events == [(event, i) for i in range(1, 10) for event in ("open", "close")]


async def test_short_flaps_do_not_reset_delay_but_sixty_seconds_initialized_does():
    now, attempts, waits = [0.0], 0, []

    async def session(emit):
        nonlocal attempts
        attempts += 1
        if attempts == 4:
            return
        if attempts > 1:
            emit("OFFICIAL_MCP_INITIALIZED")
            now[0] += 59 if attempts == 2 else 60
        raise BridgeError("OFFICIAL_MCP_REMOTE_CLOSED", retryable=True)

    async def sleep(seconds):
        waits.append(seconds)

    await runtime().run_reconnecting(
        session, emit=lambda s: None, sleep=sleep, clock=lambda: now[0]
    )
    assert waits == [2, 4, 2]


async def test_cancel_during_backoff_never_dials_again():
    waiting, calls = asyncio.Event(), []

    async def session(emit):
        calls.append(1)
        raise BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)

    async def sleep(seconds):
        waiting.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        runtime().run_reconnecting(session, emit=lambda s: None, sleep=sleep)
    )
    await asyncio.wait_for(waiting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [1]


async def test_fatal_failure_or_output_error_does_not_retry():
    calls = []

    async def fatal(emit):
        calls.append(1)
        raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")

    async def forbidden_sleep(seconds):
        pytest.fail("fatal failure retried")

    with pytest.raises(BridgeError):
        await runtime().run_reconnecting(fatal, emit=lambda s: None, sleep=forbidden_sleep)
    assert calls == [1]

    async def network(emit):
        raise BridgeError("OFFICIAL_MCP_CONNECTION_FAILED", retryable=True)

    def unavailable_output(line):
        raise OSError("private-output")

    with pytest.raises(BridgeError) as caught:
        await runtime().run_reconnecting(network, emit=unavailable_output, sleep=forbidden_sleep)
    assert caught.value.code == "OFFICIAL_MCP_OUTPUT_FAILED"


@pytest.mark.parametrize("close_code,recover", [(1000, True), (1008, False), (1011, True)])
async def test_real_remote_close_reinitializes_only_temporary_sessions(
    monkeypatch, close_code, recover
):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    module = bridge_module()
    peers, reports = [], []
    closed = asyncio.Event()

    async def peer(socket):
        peers.append(1)
        await initialize(socket)
        await request(socket, 2, "tools/list", {})
        if len(peers) == 1:
            await socket.close(code=close_code, reason="synthetic-private-reason")
        else:
            closed.set()
            await socket.wait_closed()

    async with serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        @asynccontextmanager
        async def local_only(uri, **kwargs):
            assert uri == ENDPOINT
            async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                yield socket

        monkeypatch.setattr(module, "connect", local_only)

        async def session(emit):
            await run_bridge(ENDPOINT, emit=emit)

        async def sleep(seconds):
            assert seconds == 2

        task = asyncio.create_task(
            runtime().run_reconnecting(session, emit=reports.append, sleep=sleep)
        )
        if recover:
            await asyncio.wait_for(closed.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(peers) == 2 and reports.count("OFFICIAL_MCP_INITIALIZED") == 2
            assert len([r for r in reports if r.startswith("PC_CHECK_CODE=")]) == 2
        else:
            with pytest.raises(BridgeError) as caught:
                await asyncio.wait_for(task, 3)
            assert caught.value.retryable is False and len(peers) == 1
    assert "private" not in str(reports)
