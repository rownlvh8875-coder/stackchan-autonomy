"""Exercise the PC tool through a real local WebSocket and the pinned MCP SDK."""

import asyncio
import importlib
import json
import logging
import re
from contextlib import asynccontextmanager, suppress

import pytest

ENDPOINT = "wss://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret"


def bridge_module():
    return importlib.import_module("stackchan_autonomy.official_mcp")


async def request(socket, request_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    await socket.send(json.dumps(message))
    return json.loads(await asyncio.wait_for(socket.recv(), 3))


async def initialize(socket, *, notification_params=None):
    response = await request(
        socket,
        1,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "offline-endpoint", "version": "1"},
        },
    )
    assert response["id"] == 1 and "result" in response
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    if notification_params is not None:
        notification["params"] = notification_params
    await socket.send(json.dumps(notification))


@asynccontextmanager
async def local_endpoint(module, monkeypatch, peer, *, emit=None, wrap=None):
    """Replace only the external dial; keep the actual WebSocket/SDK dialogue."""
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    result = asyncio.get_running_loop().create_future()
    hold = asyncio.Event()
    lines = [] if emit is None else emit

    async def handler(socket):
        try:
            value = await peer(socket)
            if not result.done():
                result.set_result(value)
            await hold.wait()
        except Exception as error:
            if not result.done():
                result.set_exception(error)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        @asynccontextmanager
        async def dial(uri, **kwargs):
            assert uri == ENDPOINT
            async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                yield wrap(socket) if wrap is not None else socket

        monkeypatch.setattr(module, "connect", dial)
        task = asyncio.create_task(module.run_bridge(ENDPOINT, emit=lines.append))
        try:
            yield task, result, lines
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, module.BridgeError):
                await task
            hold.set()
            if result.done() and not result.cancelled():
                result.exception()


@pytest.mark.parametrize(
    "value",
    [
        "http://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret",
        "ws://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret",
        "wss://api.xiaozhi.me.example.org/mcp/?token=synthetic-endpoint-secret",
        "wss://user@api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret",
        "wss://api.xiaozhi.me:444/mcp/?token=synthetic-endpoint-secret",
        "wss://api.xiaozhi.me/other?token=synthetic-endpoint-secret",
        "wss://api.xiaozhi.me/mcp/?token=one&token=synthetic-endpoint-secret",
        "wss://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret&extra=1",
        "wss://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret#fragment",
        "wss://api.xiaozhi.me/mcp/?token=",
        "wss://api.xiaozhi.me/mcp/",
        "wss://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret%0A",
        "wss://api.xiaozhi.me/mcp/?token=synthetic-endpoint-secret\r\nInjected:yes",
        "wss://api.xiaozhi.me/mcp/?token=" + "a" * 8192,
    ],
)
def test_rejects_unsafe_endpoint_without_disclosing_it(value, capsys, caplog):
    module = bridge_module()
    with pytest.raises(module.BridgeError) as caught:
        module.validate_endpoint(value)
    observed = str(caught.value) + repr(caught.value) + caplog.text + str(capsys.readouterr())
    assert "synthetic-endpoint-secret" not in observed
    assert "api.xiaozhi.me" not in observed


@pytest.mark.parametrize(
    "value",
    [ENDPOINT, ENDPOINT.replace("/mcp/", "/mcp"), ENDPOINT.replace(".me/", ".me:443/")],
)
def test_copied_official_endpoint_accepts_only_outer_whitespace(value):
    module = bridge_module()
    assert module.validate_endpoint(" \n" + value + "\r\n") == value


def test_error_boundary_cannot_turn_arbitrary_exception_text_into_a_public_code():
    module = bridge_module()
    error = module.BridgeError("synthetic-endpoint-secret at " + ENDPOINT)
    assert "synthetic-endpoint-secret" not in str(error) + error.code


async def test_real_mcp_dialogue_lists_and_invokes_only_connection_status(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket)
        listing = await request(socket, 2, "tools/list", {})
        tools = listing["result"]["tools"]
        assert [tool["name"] for tool in tools] == ["stackchan_pc_connection_status"]
        assert tools[0]["inputSchema"]["additionalProperties"] is False
        assert tools[0]["inputSchema"]["properties"] == {}
        first = await request(
            socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )
        second = await request(
            socket, 4, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )
        return first["result"]["structuredContent"], second["result"]["structuredContent"]

    async with local_endpoint(module, monkeypatch, peer) as (task, result, lines):
        first, second = await asyncio.wait_for(result, 5)
        assert not task.done()
        assert set(first) == {
            "service",
            "check_code",
            "uptime_s",
            "call_count",
            "robot_control_available",
        }
        assert first["service"] == "stackchan-pc"
        assert re.fullmatch(r"\d{6}", first["check_code"])
        assert first["check_code"] == second["check_code"]
        assert [first["call_count"], second["call_count"]] == [1, 2]
        assert 0 <= first["uptime_s"] <= second["uptime_s"]
        assert first["robot_control_available"] is second["robot_control_available"] is False
        assert any(first["check_code"] in line for line in lines)
        assert "synthetic-endpoint-secret" not in "\n".join(lines)


async def test_protocol_ping_is_allowed_before_initialization(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        ping = await request(socket, 0, "ping", {})
        assert ping["result"] == {}
        await initialize(socket)
        return await request(socket, 2, "tools/list", {})

    async with local_endpoint(module, monkeypatch, peer) as (_, result, _):
        listing = await asyncio.wait_for(result, 5)
        assert len(listing["result"]["tools"]) == 1


async def test_initialized_notification_accepts_standard_metadata(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket, notification_params={"_meta": {"client": "official-endpoint"}})
        return await request(socket, 2, "tools/list", {})

    async with local_endpoint(module, monkeypatch, peer) as (_, result, _):
        listing = await asyncio.wait_for(result, 5)
        assert len(listing["result"]["tools"]) == 1


async def test_catalog_after_initialize_reply_matches_sdk_compatible_clients(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        response = await request(
            socket,
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sdk-compatible-endpoint", "version": "1"},
            },
        )
        assert "result" in response
        listing = await request(socket, 2, "tools/list", {})
        assert len(listing["result"]["tools"]) == 1
        await socket.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        return await request(
            socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )

    async with local_endpoint(module, monkeypatch, peer) as (task, result, lines):
        called = await asyncio.wait_for(result, 5)
        assert not task.done()
        assert called["result"]["structuredContent"]["call_count"] == 1
        assert len([line for line in lines if line.startswith("PC_CHECK_CODE=")]) == 1


async def test_rejected_tool_calls_cannot_increment_real_call_count(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket)
        await request(socket, 2, "tools/list", {})
        extra = await request(
            socket,
            3,
            "tools/call",
            {"name": "stackchan_pc_connection_status", "arguments": {"command": "do-not-execute"}},
        )
        unknown = await request(socket, 4, "tools/call", {"name": "run_shell", "arguments": {}})
        valid = await request(
            socket, 5, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )
        return extra, unknown, valid

    async with local_endpoint(module, monkeypatch, peer) as (_, result, _):
        extra, unknown, valid = await asyncio.wait_for(result, 5)
        assert extra["result"]["isError"] is True
        assert unknown["result"]["isError"] is True
        assert valid["result"]["structuredContent"]["call_count"] == 1


async def test_connected_endpoint_that_never_initializes_times_out_and_closes(monkeypatch):
    module = bridge_module()
    monkeypatch.setattr(module, "INITIALIZATION_TIMEOUT_S", 0.1, raising=False)
    closed = asyncio.Event()

    async def peer(socket):
        await socket.wait_closed()
        closed.set()

    async with local_endpoint(module, monkeypatch, peer) as (task, _, _):
        with pytest.raises(module.BridgeError):
            await asyncio.wait_for(asyncio.shield(task), 2)
        await asyncio.wait_for(closed.wait(), 1)


@pytest.mark.parametrize(
    "frame",
    [
        b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        "not-json synthetic-endpoint-secret",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/unexpected"}),
        "x" * 20000,
    ],
)
async def test_bad_frames_fail_closed_without_exporting_server_text(monkeypatch, frame, caplog):
    module = bridge_module()

    async def peer(socket):
        await socket.send(frame)
        await socket.wait_closed()

    async with local_endpoint(module, monkeypatch, peer) as (task, _, lines):
        with pytest.raises(module.BridgeError) as caught:
            await asyncio.wait_for(asyncio.shield(task), 2)
        assert "synthetic-endpoint-secret" not in str(caught.value) + "\n".join(lines) + caplog.text


async def test_call_before_initialization_does_not_invoke_pc_tool(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        await socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "stackchan_pc_connection_status", "arguments": {}},
                }
            )
        )
        await socket.wait_closed()

    async with local_endpoint(module, monkeypatch, peer) as (task, _, lines):
        with pytest.raises(module.BridgeError):
            await asyncio.wait_for(asyncio.shield(task), 2)
        assert not any("PC_TOOL_CALLED" in line for line in lines)


async def test_second_initialization_is_a_protocol_fault(monkeypatch):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket)
        await socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "second", "version": "1"},
                    },
                }
            )
        )
        await socket.wait_closed()

    async with local_endpoint(module, monkeypatch, peer) as (task, _, _):
        with pytest.raises(module.BridgeError):
            await asyncio.wait_for(asyncio.shield(task), 2)


async def test_library_logging_and_connection_exceptions_do_not_leak_endpoint(
    monkeypatch, caplog, capsys
):
    module = bridge_module()

    def failing_dial(uri, **kwargs):
        logging.getLogger("websockets.client").warning("failed at %s", uri)
        logging.getLogger("mcp.server.lowlevel.server").warning("received %s", uri)
        raise OSError("private server reason " + uri)

    monkeypatch.setattr(module, "connect", failing_dial)
    with caplog.at_level(logging.DEBUG), pytest.raises(module.BridgeError) as caught:
        await module.run_bridge(ENDPOINT, emit=print)
    observed = caplog.text + str(capsys.readouterr()) + str(caught.value)
    assert "synthetic-endpoint-secret" not in observed
    assert "private server reason" not in observed
    assert "api.xiaozhi.me" not in observed


@pytest.mark.parametrize(
    "method,params",
    [
        ("tools/call", {"name": ["synthetic-review-secret"]}),
        ("synthetic-review-secret", {}),
    ],
)
async def test_sdk_typed_validation_cannot_leak_via_root_logger(
    monkeypatch, caplog, capsys, method, params
):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket)
        invalid = await request(socket, 2, method, params)
        assert "error" in invalid
        return await request(
            socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )

    with caplog.at_level(logging.DEBUG):
        async with local_endpoint(module, monkeypatch, peer) as (_, result, lines):
            valid = await asyncio.wait_for(result, 5)
            assert valid["result"]["structuredContent"]["call_count"] == 1
        observed = caplog.text + str(capsys.readouterr()) + "\n".join(lines)
    assert "synthetic-review-secret" not in observed


async def test_malformed_initialized_notification_is_private_and_not_marked_ready(
    monkeypatch, caplog, capsys
):
    module = bridge_module()

    async def peer(socket):
        await request(
            socket,
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "offline-endpoint", "version": "1"},
            },
        )
        await socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {"_meta": ["synthetic-review-secret"]},
                }
            )
        )
        await socket.wait_closed()

    with caplog.at_level(logging.DEBUG):
        async with local_endpoint(module, monkeypatch, peer) as (task, _, lines):
            with pytest.raises(module.BridgeError):
                await asyncio.wait_for(asyncio.shield(task), 2)
            assert "OFFICIAL_MCP_INITIALIZED" not in lines
        observed = caplog.text + str(capsys.readouterr()) + "\n".join(lines)
    assert "synthetic-review-secret" not in observed


@pytest.mark.parametrize("cancelled_id", [2, 999])
async def test_standard_late_or_unknown_cancellation_keeps_session_usable(
    monkeypatch, cancelled_id
):
    module = bridge_module()

    async def peer(socket):
        await initialize(socket)
        first = await request(
            socket, 2, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )
        await socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": cancelled_id, "reason": "user cancelled"},
                }
            )
        )
        second = await request(
            socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )
        return first["result"]["structuredContent"], second["result"]["structuredContent"]

    async with local_endpoint(module, monkeypatch, peer) as (task, result, _):
        first, second = await asyncio.wait_for(result, 5)
        assert not task.done()
        assert [first["call_count"], second["call_count"]] == [1, 2]
        assert first["check_code"] == second["check_code"]


async def test_automatic_redirect_cannot_reach_a_nonofficial_endpoint(monkeypatch):
    from http import HTTPStatus

    from websockets.asyncio.server import serve

    module = bridge_module()
    original_connect = module.connect
    target_reached = asyncio.Event()

    async def target(socket):
        target_reached.set()
        await socket.wait_closed()

    async with serve(target, "127.0.0.1", 0) as target_server:
        target_port = target_server.sockets[0].getsockname()[1]

        async def redirect(connection, request):
            response = connection.respond(HTTPStatus.FOUND, "")
            response.headers["Location"] = f"ws://127.0.0.1:{target_port}/?token=synthetic-redirect"
            return response

        async with serve(target, "127.0.0.1", 0, process_request=redirect) as redirect_server:
            port = redirect_server.sockets[0].getsockname()[1]

            def dial(uri, **kwargs):
                return original_connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs)

            monkeypatch.setattr(module, "connect", dial)
            task = asyncio.create_task(module.run_bridge(ENDPOINT, emit=lambda line: None))
            reached = asyncio.create_task(target_reached.wait())
            try:
                done, _ = await asyncio.wait(
                    {task, reached}, timeout=3, return_when=asyncio.FIRST_COMPLETED
                )
                assert done, "connection/redirect decision did not finish"
                assert not target_reached.is_set(), "redirect reached an unapproved endpoint"
                with pytest.raises(module.BridgeError):
                    await task
            finally:
                task.cancel()
                reached.cancel()
                with suppress(asyncio.CancelledError, module.BridgeError):
                    await task
                with suppress(asyncio.CancelledError):
                    await reached


async def test_cancellation_drains_the_real_sdk_and_websocket_tasks(monkeypatch):
    module = bridge_module()
    baseline = set(asyncio.all_tasks())

    async def peer(socket):
        await initialize(socket)
        return await request(socket, 2, "tools/list", {})

    async with local_endpoint(module, monkeypatch, peer) as (_, result, _):
        await asyncio.wait_for(result, 5)
    await asyncio.sleep(0)
    assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}


async def test_blocked_response_applies_backpressure_before_more_tool_work(monkeypatch):
    module = bridge_module()
    blocked, release, sent_all = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowWriter:
        def __init__(self, socket):
            self.socket = socket

        def __getattr__(self, name):
            return getattr(self.socket, name)

        async def send(self, value):
            message = json.loads(value)
            if message.get("id") == 3:
                blocked.set()
                await release.wait()
            await self.socket.send(value)

    async def peer(socket):
        await initialize(socket)
        await request(socket, 2, "tools/list", {})
        for request_id in range(3, 35):
            await socket.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": "stackchan_pc_connection_status", "arguments": {}},
                    }
                )
            )
        sent_all.set()
        return [json.loads(await socket.recv()) for _ in range(32)]

    async with local_endpoint(module, monkeypatch, peer, wrap=SlowWriter) as (_, result, lines):
        try:
            await asyncio.wait_for(blocked.wait(), 3)
            await asyncio.wait_for(sent_all.wait(), 3)
            await asyncio.sleep(0.1)
            assert len([line for line in lines if "PC_TOOL_CALLED" in line]) == 1
        finally:
            release.set()
        responses = await asyncio.wait_for(result, 5)
        assert {response["id"] for response in responses} == set(range(3, 35))
        assert sorted(
            response["result"]["structuredContent"]["call_count"] for response in responses
        ) == list(range(1, 33))
