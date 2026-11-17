"""Bounded read-only PC tools served to the official AI over an outbound WebSocket."""

import secrets
import time
from collections.abc import Callable
from urllib.parse import parse_qsl, urlsplit

import anyio
from mcp import types
from mcp.server import Server
from mcp.shared.message import SessionMessage
from websockets.asyncio.client import connect as _WebSocketConnect
from websockets.exceptions import ConnectionClosed

from .gpt_chat import GPTChat, GPTChatError
from .private_logging import private_library_logs as _private_library_logs
from .soak_summary import SoakSummaryUnavailable, load_soak_summary

INITIALIZATION_TIMEOUT_S = 30.0
_INPUT_LIMIT = 16 * 1024
_OUTPUT_LIMIT = 64 * 1024
_TOOL_NAME = "stackchan_pc_connection_status"
_SUMMARY_TOOL_NAME = "stackchan_pc_soak_report_summary"
_GPT_TOOL_NAME = "stackchan_gpt_reply"
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
        "PC_SOAK_REPORT_UNAVAILABLE",
        "PC_GPT_CONFIG_REQUIRED",
        "PC_GPT_INVALID_QUESTION",
        "PC_GPT_BUDGET_EXHAUSTED",
        "PC_GPT_STORAGE_UNAVAILABLE",
        "PC_GPT_UNAVAILABLE",
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


def _failure_code(error: Exception) -> str:
    if isinstance(error, BridgeError):
        return error.code
    if isinstance(error, ExceptionGroup):
        for child in error.exceptions:
            code = _failure_code(child)
            if code != "OFFICIAL_MCP_CONNECTION_FAILED":
                return code
    return "OFFICIAL_MCP_CONNECTION_FAILED"


async def run_bridge(
    endpoint: str, *, emit: Callable[[str], None], gpt: GPTChat | None = None
) -> None:
    endpoint = validate_endpoint(endpoint)
    with _private_library_logs():
        try:
            await _run(endpoint, emit, gpt)
        except Exception as error:
            raise BridgeError(_failure_code(error)) from None


async def _run(endpoint: str, emit: Callable[[str], None], gpt: GPTChat | None) -> None:
    check_code = str(secrets.randbelow(900000) + 100000)
    started_at = time.monotonic()
    call_count = 0
    summary_call_count = 0
    gpt_call_count = 0
    server = Server("stackchan-pc", version="0.1.0")

    def report(line: str):
        try:
            emit(line)
        except Exception:
            raise BridgeError("OFFICIAL_MCP_OUTPUT_FAILED") from None

    @server.list_tools()
    async def list_tools():
        tools = [
            types.Tool(
                name=_TOOL_NAME,
                description="PC 연결 상태와 현재 실행의 6자리 연결 확인 코드를 알려줍니다. 로봇 제어 기능은 없습니다.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, openWorldHint=False
                ),
            ),
            types.Tool(
                name=_SUMMARY_TOOL_NAME,
                description=(
                    "24시간 시험 결과 알려줘: 2026-11-15에 접수된 과거 PC 가상 로봇(Fake/Mock) "
                    "시험 보고서의 통과 여부와 수치를 조회합니다. 실제 경과 시간 시험이며 "
                    "실물 로봇 24시간 검증이나 현재 실행 상태가 아닙니다. 날짜는 실행일이 아닌 "
                    "보고서 접수일이고 메모리는 Python 추적 증가량입니다. 응답 시 이 범위를 설명하세요."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, openWorldHint=False
                ),
            ),
        ]
        if gpt is not None:
            tools.append(
                types.Tool(
                    name=_GPT_TOOL_NAME,
                    description=(
                        "GPT에게 질문하거나 일반 대화 답변을 요청할 때 사용합니다. PC의 OpenAI API로 "
                        "답변을 생성하며 사용량 비용이 발생합니다. 질문만 question에 넣으세요. 성공하면 "
                        "answer를 자연스러운 한국어로 그대로 읽고, 실패하면 GPT 연결 실패를 알리세요. "
                        "하드웨어 제어 기능은 없습니다."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "minLength": 1, "maxLength": 1200}
                        },
                        "required": ["question"],
                        "additionalProperties": False,
                    },
                    annotations=types.ToolAnnotations(
                        readOnlyHint=True, destructiveHint=False, openWorldHint=True
                    ),
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        nonlocal call_count, summary_call_count, gpt_call_count
        if name == _GPT_TOOL_NAME and gpt is not None:
            if set(arguments) != {"question"}:
                raise BridgeError("PC_GPT_INVALID_QUESTION")
            gpt_call_count += 1
            report(f"PC_GPT_CALLED={gpt_call_count}")
            try:
                reply = await gpt.ask(arguments["question"])
            except GPTChatError as error:
                report(error.code)
                raise BridgeError(error.code) from None
            report(f"PC_GPT_ANSWERED={gpt_call_count}")
            return reply
        if name not in {_TOOL_NAME, _SUMMARY_TOOL_NAME} or arguments:
            raise BridgeError("PC_TOOL_UNSUPPORTED")
        if name == _SUMMARY_TOOL_NAME:
            summary_call_count += 1
            report(f"PC_SOAK_REPORT_CALLED={summary_call_count}")
            try:
                return load_soak_summary()
            except SoakSummaryUnavailable:
                report("PC_SOAK_REPORT_UNAVAILABLE")
                raise BridgeError("PC_SOAK_REPORT_UNAVAILABLE") from None
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
                if gpt is not None:
                    report("PC_GPT_READY")

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
