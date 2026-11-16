"""A single read-only PC tool served to the official AI over an outbound WebSocket."""

import logging
import secrets
import time
from collections.abc import Callable
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlsplit

import anyio
from mcp import types
from mcp.server import Server
from mcp.shared.message import SessionMessage
from websockets.asyncio.client import connect as _WebSocketConnect
from websockets.exceptions import ConnectionClosed

INITIALIZATION_TIMEOUT_S = 30.0
_INPUT_LIMIT = 16 * 1024
_OUTPUT_LIMIT = 64 * 1024
_TOOL_NAME = "stackchan_pc_connection_status"
_ERROR_CODES = frozenset(
    {
        "OFFICIAL_MCP_INVALID_ENDPOINT",
        "OFFICIAL_MCP_CONNECTION_FAILED",
        "OFFICIAL_MCP_PROTOCOL_FAILED",
        "OFFICIAL_MCP_REMOTE_CLOSED",
        "OFFICIAL_MCP_INITIALIZATION_TIMEOUT",
        "OFFICIAL_MCP_OUTPUT_FAILED",
        "OFFICIAL_MCP_REDIRECT_REJECTED",
        "PC_TOOL_UNSUPPORTED",
    }
)


class BridgeError(Exception):
    """Only fixed public codes cross the transport/console boundary."""

    def __init__(self, code: str):
        self.code = code if code in _ERROR_CODES else "OFFICIAL_MCP_CONNECTION_FAILED"
        super().__init__(self.code)


class _SingleEndpointConnect(_WebSocketConnect):
    def process_redirect(self, error: Exception) -> Exception | str:
        result = super().process_redirect(error)
        if isinstance(result, str):
            return BridgeError("OFFICIAL_MCP_REDIRECT_REJECTED")
        return result


connect = _SingleEndpointConnect


def validate_endpoint(value: str) -> str:
    """Validate the operator's endpoint without putting its value in an error."""
    try:
        endpoint = value.strip()
        if not endpoint or len(endpoint) > 8192:
            raise ValueError
        if any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in endpoint
        ):
            raise ValueError
        parts = urlsplit(endpoint)
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        if (
            parts.scheme != "wss"
            or parts.netloc.lower() not in {"api.xiaozhi.me", "api.xiaozhi.me:443"}
            or parts.path not in {"/mcp", "/mcp/"}
            or parts.fragment
            or len(query) != 1
            or query[0][0] != "token"
            or not query[0][1]
            or any(
                character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in query[0][1]
            )
        ):
            raise ValueError
        return endpoint
    except (AttributeError, TypeError, ValueError):
        raise BridgeError("OFFICIAL_MCP_INVALID_ENDPOINT") from None


@contextmanager
def _private_library_logs():
    """Keep SDK/transport messages out of the dedicated bridge's console/logs."""
    roots = ("mcp", "websockets")
    for name in roots:
        logging.getLogger(name)
    loggers = [
        logger
        for name, logger in list(logging.Logger.manager.loggerDict.items())
        if isinstance(logger, logging.Logger)
        and any(name == root or name.startswith(root + ".") for root in roots)
    ]
    # MCP1.30 also calls logging.warning/debug directly for typed validation.
    # This is a dedicated process; protect and later restore the root handlers too.
    loggers.append(logging.getLogger())
    previous = [(logger, logger.handlers[:], logger.propagate) for logger in loggers]
    try:
        for logger in loggers:
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
        yield
    finally:
        for logger, handlers, propagate in previous:
            logger.handlers = handlers
            logger.propagate = propagate


def _failure_code(error: Exception) -> str:
    if isinstance(error, BridgeError):
        return error.code
    if isinstance(error, ExceptionGroup):
        for child in error.exceptions:
            code = _failure_code(child)
            if code != "OFFICIAL_MCP_CONNECTION_FAILED":
                return code
    return "OFFICIAL_MCP_CONNECTION_FAILED"


async def run_bridge(endpoint: str, *, emit: Callable[[str], None]) -> None:
    endpoint = validate_endpoint(endpoint)
    with _private_library_logs():
        try:
            await _run(endpoint, emit)
        except Exception as error:
            raise BridgeError(_failure_code(error)) from None


async def _run(endpoint: str, emit: Callable[[str], None]) -> None:
    check_code = str(secrets.randbelow(900000) + 100000)
    started_at = time.monotonic()
    call_count = 0
    server = Server("stackchan-pc", version="0.1.0")

    def report(line: str):
        try:
            emit(line)
        except Exception:
            raise BridgeError("OFFICIAL_MCP_OUTPUT_FAILED") from None

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name=_TOOL_NAME,
                description="PC 연결 상태와 현재 실행의 6자리 연결 확인 코드를 알려줍니다. 로봇 제어 기능은 없습니다.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, openWorldHint=False
                ),
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        nonlocal call_count
        if name != _TOOL_NAME or arguments:
            raise BridgeError("PC_TOOL_UNSUPPORTED")
        call_count += 1
        report(f"PC_TOOL_CALLED={call_count}")
        return {
            "service": "stackchan-pc",
            "check_code": check_code,
            "uptime_s": round(time.monotonic() - started_at, 3),
            "call_count": call_count,
            "robot_control_available": False,
        }

    report("OFFICIAL_MCP_CONNECTING")
    async with connect(
        endpoint,
        open_timeout=10,
        close_timeout=5,
        max_size=_INPUT_LIMIT,
        max_queue=16,
        write_limit=_OUTPUT_LIMIT,
        ping_interval=20,
        ping_timeout=20,
    ) as socket:
        report("OFFICIAL_MCP_CONNECTED")
        incoming, read_stream = anyio.create_memory_object_stream[SessionMessage](16)
        write_stream, outgoing = anyio.create_memory_object_stream[SessionMessage](16)
        initialized = anyio.Event()
        stage = "new"
        init_response_sent = False
        initialized_notification_seen = False
        pending_id: str | int | None = None
        pending_method: str | None = None
        response_sent: anyio.Event | None = None

        def mark_ready():
            nonlocal stage
            stage = "ready"
            if not initialized.is_set():
                initialized.set()
                report("OFFICIAL_MCP_INITIALIZED")
                report(f"PC_CHECK_CODE={check_code}")

        async def read_socket():
            nonlocal stage, pending_id, pending_method, response_sent, initialized_notification_seen
            while True:
                try:
                    frame = await socket.recv()
                except ConnectionClosed:
                    raise BridgeError("OFFICIAL_MCP_REMOTE_CLOSED") from None
                if not isinstance(frame, str) or len(frame.encode("utf-8")) > _INPUT_LIMIT:
                    raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")
                try:
                    message = types.JSONRPCMessage.model_validate_json(frame)
                except Exception:
                    raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED") from None
                root = message.root
                if isinstance(root, types.JSONRPCRequest):
                    if root.method == "initialize":
                        if stage != "new":
                            raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")
                        stage = "initializing"
                    else:
                        # MCP1.30 accepts requests after the initialize reply. Some
                        # compatible clients list tools before sending the notification.
                        if stage == "initializing" and init_response_sent:
                            mark_ready()
                        if root.method != "ping" and stage != "ready":
                            raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")
                    pending_id, pending_method = root.id, root.method
                    response_sent = anyio.Event()
                    await incoming.send(SessionMessage(message))
                    # Admit only one SDK request until its response is on the wire.
                    # A queue alone would not bound the SDK's spawned request tasks.
                    await response_sent.wait()
                    pending_id = pending_method = response_sent = None
                elif (
                    isinstance(root, types.JSONRPCNotification)
                    and root.method == "notifications/initialized"
                    and stage in {"initializing", "ready"}
                    and init_response_sent
                    and not initialized_notification_seen
                ):
                    try:
                        types.InitializedNotification.model_validate(root.model_dump())
                    except Exception:
                        raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED") from None
                    initialized_notification_seen = True
                    await incoming.send(SessionMessage(message))
                    mark_ready()
                elif (
                    isinstance(root, types.JSONRPCNotification)
                    and root.method == "notifications/cancelled"
                ):
                    try:
                        types.CancelledNotification.model_validate(root.model_dump())
                    except Exception:
                        raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED") from None
                    # The serial reader cannot process cancellation until the prior
                    # response is written. Completed/unknown IDs are harmless no-ops;
                    # forwarding them would add unnecessary SDK notification work.
                else:
                    raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")

        async def write_socket():
            nonlocal init_response_sent
            async for message in outgoing:
                payload = message.message.model_dump_json(by_alias=True, exclude_none=True)
                if len(payload.encode("utf-8")) > _OUTPUT_LIMIT:
                    raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")
                await socket.send(payload)
                root = message.message.root
                if (
                    isinstance(root, (types.JSONRPCResponse, types.JSONRPCError))
                    and root.id == pending_id
                ):
                    if pending_method == "initialize":
                        if not isinstance(root, types.JSONRPCResponse):
                            raise BridgeError("OFFICIAL_MCP_PROTOCOL_FAILED")
                        init_response_sent = True
                    if pending_method == "tools/list" and isinstance(root, types.JSONRPCResponse):
                        report("OFFICIAL_MCP_TOOLS_LISTED")
                    if response_sent is not None:
                        response_sent.set()

        async def initialization_deadline():
            try:
                with anyio.fail_after(INITIALIZATION_TIMEOUT_S):
                    await initialized.wait()
            except TimeoutError:
                raise BridgeError("OFFICIAL_MCP_INITIALIZATION_TIMEOUT") from None

        async with incoming, read_stream, write_stream, outgoing:
            async with anyio.create_task_group() as group:
                group.start_soon(read_socket)
                group.start_soon(write_socket)
                group.start_soon(initialization_deadline)
                group.start_soon(
                    server.run, read_stream, write_stream, server.create_initialization_options()
                )
