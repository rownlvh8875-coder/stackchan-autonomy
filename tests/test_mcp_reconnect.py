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


@pytest.mark.parametrize("proxy", [False, True])
async def test_handshake_eof_recovers_to_a_real_mcp_session(monkeypatch, proxy):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    ready = asyncio.Event()
    dials = []

    async def drop(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
        finally:
            writer.close()
            await writer.wait_closed()

    async def peer(socket):
        await initialize(socket)
        await request(socket, 2, "tools/list", {})
        ready.set()
        await socket.wait_closed()

    module = bridge_module()
    async with await asyncio.start_server(drop, "127.0.0.1", 0) as raw:
        raw_port = raw.sockets[0].getsockname()[1]
        async with serve(peer, "127.0.0.1", 0) as good:
            good_port = good.sockets[0].getsockname()[1]

            @asynccontextmanager
            async def local_only(uri, **kwargs):
                assert uri == ENDPOINT
                dials.append(1)
                if len(dials) == 1 and proxy:
                    # The loopback proxy drops CONNECT; it never forwards externally.
                    target, route = "wss://synthetic.invalid/", f"http://127.0.0.1:{raw_port}"
                else:
                    port = raw_port if len(dials) == 1 else good_port
                    target, route = f"ws://127.0.0.1:{port}", None
                async with connect(target, proxy=route, **kwargs) as socket:
                    yield socket

            monkeypatch.setattr(module, "connect", local_only)

            async def session(emit):
                await run_bridge(ENDPOINT, emit=emit)

            async def sleep(seconds):
                assert seconds == 2

            task = asyncio.create_task(
                runtime().run_reconnecting(session, emit=lambda s: None, sleep=sleep)
            )
            try:
                await asyncio.wait_for(ready.wait(), 3)
                assert len(dials) == 2 and not task.done()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_bad_http_syntax_remains_fatal_even_though_eof_can_retry(monkeypatch):
    from websockets.exceptions import InvalidMessage, InvalidProxyMessage

    module = bridge_module()
    for cls in (InvalidMessage, InvalidProxyMessage):
        failure = cls("private-invalid-http")
        failure.__cause__ = ValueError("private-malformed-status")

        def fail(*args, **kwargs):
            raise failure

        monkeypatch.setattr(module, "connect", fail)
        with pytest.raises(BridgeError) as caught:
            await run_bridge(ENDPOINT, emit=lambda s: None)
        assert not caught.value.retryable


async def test_sdk_tool_output_failure_terminates_session_without_redial(monkeypatch):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve
    from websockets.exceptions import ConnectionClosed

    broken = asyncio.Event()
    calls = []

    async def peer(socket):
        await initialize(socket)
        await request(socket, 2, "tools/list", {})
        try:
            await request(
                socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
            )
        except ConnectionClosed:
            pass
        await socket.wait_closed()

    def unavailable(line):
        if line.startswith("PC_TOOL_CALLED="):
            broken.set()
            raise BrokenPipeError("private-output")

    module = bridge_module()
    async with serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        @asynccontextmanager
        async def local_only(uri, **kwargs):
            async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                yield socket

        monkeypatch.setattr(module, "connect", local_only)

        async def session(emit):
            calls.append(1)
            await run_bridge(ENDPOINT, emit=emit)

        async def no_retry(seconds):
            pytest.fail("output failure must be fatal")

        task = asyncio.create_task(
            runtime().run_reconnecting(session, emit=unavailable, sleep=no_retry)
        )
        try:
            await asyncio.wait_for(broken.wait(), 2)
            with pytest.raises(BridgeError) as caught:
                await asyncio.wait_for(asyncio.shield(task), 2)
            assert caught.value.code == "OFFICIAL_MCP_OUTPUT_FAILED"
            assert calls == [1]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


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
