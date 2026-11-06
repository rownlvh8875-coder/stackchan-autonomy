"""Shared MCP daemon client. Physical writes/capture remain unconditionally blocked."""

import asyncio
import base64
import binascii
import logging
import math
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import timedelta
from io import BytesIO

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
from mcp.shared._httpx_utils import create_mcp_http_client, request_within_origin
from PIL import Image
from pydantic import ValidationError

from .mcp_contract import (
    TOOL_MAP,
    GatewaySnapshot,
    HeadPose,
    MCPFailure,
    MotorAck,
    TouchState,
    json_payload,
    supports_tool,
)
from .models import Event, EventKind, Observation, RobotCommand, RobotStatus, StrictModel

_owned_transport = ContextVar("stackchan_private_mcp_transport", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        # SDK validation/debug logs may include raw response bodies. Other clients'
        # contexts retain their own logging; our callers receive fixed error codes.
        return not _owned_transport.get()


logging.getLogger("mcp.client.streamable_http").addFilter(_TransportPrivacy())
logger = logging.getLogger(__name__)


def _checked_timeout(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= 120
    ):
        raise ValueError("timeout must be finite and within (0,120]")
    return float(value)


async def _terminate_session(client, url, session_id, protocol_version, timeout_s):
    headers = {"mcp-session-id": session_id}
    if protocol_version is not None:
        headers["mcp-protocol-version"] = protocol_version
    # HTTPX timeouts limit inactivity, not an indefinitely trickling response body.
    async with asyncio.timeout(timeout_s):
        response = await request_within_origin(client, "DELETE", url, headers=headers)
        if response.status_code == 405:
            logger.warning("mcp_session_cleanup_unsupported")
            return False
        if response.status_code not in (200, 204):
            raise MCPFailure("gateway session cleanup failed; remote outcome unknown")
        return True


class CapabilityReport(StrictModel):
    connected: bool = False
    advertised: frozenset[str] = frozenset()
    available: frozenset[str] = frozenset()
    physical_execution_enabled: bool = False


class MCPRobotAdapter:
    physical = True

    def __init__(self, session: ClientSession, timeout_s: float = 10):
        self.session = session
        self.timeout_s = _checked_timeout(timeout_s)
        self.faulted = False
        self.session_cleanup_confirmed: bool | None = None
        self._lock = asyncio.Lock()
        self._tools = {}
        self._available: set[str] = set()
        self._identity: tuple[str, str] | None = None
        self._catalog_checked = False

    @classmethod
    @asynccontextmanager
    async def connect(
        cls, url: str, *, headers: dict[str, str] | None = None, timeout_s: float = 10
    ):
        timeout_s = _checked_timeout(timeout_s)
        privacy_token = _owned_transport.set(True)
        adapter = None
        body_error = None
        cleanup_failed = False
        try:
            async with create_mcp_http_client(
                headers=headers, timeout=httpx.Timeout(timeout_s)
            ) as client:
                async with streamablehttp_client(
                    url, http_client=client, terminate_on_close=False
                ) as (read, write, get_session_id):
                    protocol_version = None
                    try:
                        async with ClientSession(
                            read, write, read_timeout_seconds=timedelta(seconds=timeout_s)
                        ) as session:
                            initialized = await session.initialize()
                            protocol_version = getattr(initialized, "protocolVersion", None)
                            # Remote transports never inherit a simulator's physical=False flag.
                            adapter = MCPRobotAdapter(session, timeout_s)
                            try:
                                yield adapter
                            except BaseException as error:
                                body_error = error
                                raise
                    finally:
                        try:
                            session_id = get_session_id() if callable(get_session_id) else None
                            if session_id:
                                if adapter is not None:
                                    adapter.session_cleanup_confirmed = False
                                confirmed = await _terminate_session(
                                    client, url, session_id, protocol_version, timeout_s
                                )
                                if adapter is not None:
                                    adapter.session_cleanup_confirmed = confirmed
                                if not confirmed and body_error is not None:
                                    body_error.add_note("gateway session cleanup unconfirmed")
                        except BaseException as error:
                            cleanup_failed = True
                            if adapter is not None:
                                adapter.session_cleanup_confirmed = False
                            if body_error is not None:
                                body_error.add_note(
                                    "gateway session cleanup failed; remote outcome unknown"
                                )
                            if not isinstance(error, Exception):
                                raise
                            raise MCPFailure(
                                "gateway session cleanup failed; remote outcome unknown"
                            ) from None
        except BaseException as error:
            task = asyncio.current_task()
            if isinstance(error, asyncio.CancelledError) or (task and task.cancelling()):
                if isinstance(body_error, asyncio.CancelledError):
                    raise body_error from None
                raise asyncio.CancelledError from None
            # AnyIO may wrap errors raised by the consumer, so retain their identity.
            if body_error is not None and not isinstance(body_error, asyncio.CancelledError):
                raise body_error from None
            if not isinstance(error, Exception):
                raise
            if cleanup_failed:
                raise MCPFailure("gateway session cleanup failed; remote outcome unknown") from None
            raise MCPFailure("gateway connection failed; manual recovery required") from None
        finally:
            if adapter is not None:
                adapter.faulted = True  # Closed sessions cannot be reused or replayed.
            _owned_transport.reset(privacy_token)

    @asynccontextmanager
    async def _operation(self):
        async with self._lock:
            if self.faulted:
                raise MCPFailure("adapter fault latched; manual recovery required")
            try:
                self._catalog_checked = False
                async with asyncio.timeout(self.timeout_s):
                    yield
            except asyncio.CancelledError:
                self.faulted = True
                raise
            except (ValueError, PermissionError):
                raise
            except Exception:
                self.faulted = True
                raise MCPFailure("gateway operation failed; no automatic replay") from None

    async def _call(self, tool: str, arguments: dict):
        try:
            return await self.session.call_tool(tool, arguments)
        except asyncio.CancelledError:
            raise
        except Exception:
            # SDK ValidationError is a ValueError, but remote decoding is not local rejection.
            raise MCPFailure("invalid or failed gateway RPC") from None

    async def _refresh(self):
        try:
            snapshot = GatewaySnapshot.model_validate(
                json_payload(await self._call("get_status", {}))
            )
        except ValidationError:
            raise MCPFailure("invalid gateway status") from None
        if (
            not snapshot.connected
            or not snapshot.initialized
            or not snapshot.device_id
            or not snapshot.session_id
            or snapshot.tools_count != len(snapshot.tools)
        ):
            raise MCPFailure("device is not initialized and connected")
        identity = (snapshot.device_id, snapshot.session_id)
        if self._identity is not None and identity != self._identity:
            raise MCPFailure("device or session changed; manual recovery required")
        self._identity = identity
        self._available = {
            capability
            for capability, (name, firmware_name) in TOOL_MAP.items()
            if name in self._tools
            and supports_tool(name, self._tools[name].inputSchema)
            and (firmware_name is None or firmware_name in snapshot.tools)
            and (not self.physical or capability not in {"capture", "speak", "listen"})
        }
        return snapshot

    async def _discover(self):
        collected = {}
        cursor = None
        for _ in range(10):
            try:
                page = await self.session.list_tools(cursor=cursor)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise MCPFailure("invalid or failed tool discovery") from None
            for tool in page.tools:
                if tool.name in collected or len(collected) >= 256:
                    raise MCPFailure("ambiguous or excessive tool catalog")
                collected[tool.name] = tool
            cursor = page.nextCursor
            if cursor is None:
                break
        else:
            raise MCPFailure("tool pagination limit")
        self._tools = collected
        self._catalog_checked = True
        status = self._tools.get("get_status")
        if status is None or not supports_tool("get_status", status.inputSchema):
            raise MCPFailure("unsupported status schema")
        return await self._refresh()

    async def discover(self) -> CapabilityReport:
        try:
            async with self._operation():
                await self._discover()
                return CapabilityReport(
                    connected=True,
                    advertised=frozenset(self._tools),
                    available=frozenset(self._available),
                )
        except MCPFailure:
            return CapabilityReport(advertised=frozenset(self._tools))

    async def _ready(self, capability: str):
        if not self._catalog_checked:
            await self._discover()
        else:
            await self._refresh()
        if capability not in self._available:
            raise ValueError("required capability is unavailable")

    async def _pose(self):
        await self._ready("pose")
        payload = json_payload(await self._call("get_head_angles", {}))
        if payload.get("servo_ok") is False:
            raise MCPFailure("servo pose unavailable")
        try:
            pose = HeadPose.model_validate(payload)
        except ValidationError:
            raise MCPFailure("invalid or unsafe absolute pose") from None
        await self._refresh()
        return pose

    async def status(self) -> RobotStatus:
        async with self._operation():
            pose = await self._pose()
            return RobotStatus(
                yaw=pose.yaw, pitch=pose.pitch, capabilities=frozenset(self._available)
            )

    def _require_simulation(self):
        if self.physical:
            raise PermissionError("physical actuation/media is disabled; simulation factory only")

    async def capture(self) -> Observation:
        self._require_simulation()
        async with self._operation():
            await self._ready("capture")
            result = await self._call("take_photo", {"question": "현재 주변 상황을 관찰합니다."})
            json_payload(result)  # Receipt paths are never read or deleted.
            images = [block for block in result.content if block.type == "image"]
            if len(images) != 1 or images[0].mimeType != "image/jpeg":
                raise MCPFailure("missing supported inline JPEG")
            encoded = images[0].data
            if len(encoded) > 280_000:
                raise MCPFailure("inline photo too large")
            try:
                data = base64.b64decode(encoded, validate=True)
                if len(data) > 200 * 1024:
                    raise ValueError
                with Image.open(BytesIO(data)) as image:
                    if image.format != "JPEG" or image.width * image.height > 4_000_000:
                        raise ValueError
                    image.verify()
            except (ValueError, OSError, binascii.Error):
                raise MCPFailure("invalid inline JPEG") from None
            await self._refresh()
            return Observation(image=data, image_mime="image/jpeg")

    async def execute(self, command: RobotCommand) -> None:
        self._require_simulation()
        command = RobotCommand.model_validate(command.model_dump())
        async with self._operation():
            if command.kind == "move":
                if command.speech or command.emotion != "idle":
                    raise ValueError("compound commands disabled")
                pose = await self._pose()
                await self._ready("move")
                yaw, pitch = round(command.yaw), round(command.pitch)
                if (
                    not -90 <= command.yaw <= 90
                    or not 5 <= command.pitch <= 85
                    or max(
                        abs(command.yaw - pose.yaw),
                        abs(command.pitch - pose.pitch),
                        abs(yaw - pose.yaw),
                        abs(pitch - pose.pitch),
                    )
                    > 15
                ):
                    raise ValueError("unsafe absolute target or quantized step")
                if yaw == pose.yaw and pitch == pose.pitch:
                    return  # The absolute target is already reached; never replay it.
                tool, args = "move_head", {"yaw": yaw, "pitch": pitch, "speed": "low"}
            elif command.kind == "emote":
                await self._ready("emote")
                faces = self._tools["set_avatar"].inputSchema["properties"]["face"]["enum"]
                if (
                    command.emotion not in faces
                    or command.emotion == "off"
                    or command.speech
                    or command.yaw != 0
                    or command.pitch != 45
                ):
                    raise ValueError("unsupported or compound expression")
                tool, args = "set_avatar", {"face": command.emotion}
            else:
                await self._ready("speak")
                if (
                    not command.speech.strip()
                    or len(command.speech) > 500
                    or command.emotion != "idle"
                    or command.yaw != 0
                    or command.pitch != 45
                ):
                    raise ValueError("invalid or compound speech")
                tool, args = "say", {"text": command.speech}
            payload = json_payload(await self._call(tool, args))
            if tool == "move_head":
                try:
                    ack = MotorAck.model_validate(payload)
                except ValidationError:
                    raise MCPFailure("invalid motor acknowledgement") from None
                if (
                    not ack.servo_init_ok
                    or (yaw != pose.yaw and not ack.yaw_motion_started)
                    or (pitch != pose.pitch and not ack.pitch_motion_started)
                ):
                    raise MCPFailure("motor dispatch is uncertain; manual recovery required")
            elif tool == "say":
                if payload.get("spoke") is not True:
                    raise MCPFailure("speech not acknowledged")
            elif payload.get("ok") is not True:
                raise MCPFailure("expression not acknowledged")
            await self._refresh()

    async def set_blink(self, enabled: bool):
        self._require_simulation()
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        async with self._operation():
            await self._ready("blink")
            payload = json_payload(await self._call("set_blink", {"enabled": enabled}))
            if payload.get("ok") is not True:
                raise MCPFailure("blink not acknowledged")
            await self._refresh()

    async def set_all_leds(self, r: int, g: int, b: int):
        self._require_simulation()
        if any(type(c) is not int or not 0 <= c <= 255 for c in (r, g, b)):
            raise ValueError("RGB must be integers in 0..255")
        async with self._operation():
            await self._ready("led")
            payload = json_payload(await self._call("set_all_leds", {"r": r, "g": g, "b": b}))
            if payload.get("available") is not True or payload.get("ok") is not True:
                raise MCPFailure("LEDs not acknowledged")
            await self._refresh()

    async def touch_state(self) -> TouchState | None:
        async with self._operation():
            await self._ready("touch")
            try:
                touch = TouchState.model_validate(
                    json_payload(await self._call("get_touch_state", {}))
                )
            except ValidationError:
                raise MCPFailure("invalid touch state") from None
            await self._refresh()
            return touch if touch.available else None

    async def listen(self, duration_ms: int = 5000) -> Event:
        self._require_simulation()
        if type(duration_ms) is not int or not 100 <= duration_ms <= 30000:
            raise ValueError("duration must be in 100..30000ms")
        async with self._operation():
            await self._ready("listen")
            payload = json_payload(
                await self._call(
                    "listen", {"duration_ms": duration_ms, "language": "ko", "motion": "none"}
                )
            )
            text = payload.get("text")
            if not isinstance(text, str) or len(text) > 500:
                raise MCPFailure("invalid transcript envelope")
            await self._refresh()
            return Event(kind=EventKind.VOICE_REQUEST, text=text)
