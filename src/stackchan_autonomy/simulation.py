"""Factory-owned in-memory MCP gateway. Never connects to a remote endpoint."""

import base64
import inspect
import json
from collections import deque
from contextlib import asynccontextmanager
from importlib.resources import files
from io import BytesIO

from mcp import types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session
from PIL import Image

from .mcp_contract import TOOL_MAP
from .mcp_robot import MCPRobotAdapter
from .models import RobotCommand
from .robot import FakeRobotAdapter


class GatewaySimulator:
    """Bounded fake state, including injectable reply failures for protocol experiments."""

    def __init__(self, *, transcript: str = "안녕하세요", history_size: int = 100):
        self.robot = FakeRobotAdapter(history_size=history_size)
        self.transcript = transcript
        self.session_id = "simulation-session-1"
        self.device_id = "simulation-robot"
        self.connected = True
        self.blink = True
        self.led = (0, 0, 0)
        self.touch = "idle"
        self.calls: deque = deque(maxlen=history_size)
        self.responses: dict = {}
        self.server = Server("stackchan-autonomy-simulator")
        self.schemas = json.loads(
            files("stackchan_autonomy")
            .joinpath("data/upstream_mcp_tools.json")
            .read_text(encoding="utf-8")
        )["tools"]

        @self.server.list_tools()
        async def list_tools():
            return [types.Tool(**tool) for tool in self.schemas]

        @self.server.call_tool()
        async def call_tool(name, arguments):
            self.calls.append((name, dict(arguments)))
            if name in self.responses:
                response = self.responses[name]
                if callable(response):
                    response = response(arguments)
                    if inspect.isawaitable(response):
                        response = await response
                return response
            return await self._reply(name, arguments)

    @staticmethod
    def _text(data: dict):
        return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    async def _reply(self, name, arguments):
        if name == "get_status":
            tools = [firmware for _, firmware in TOOL_MAP.values() if firmware]
            return self._text(
                {
                    "connected": self.connected,
                    "initialized": self.connected,
                    "device_id": self.device_id,
                    "session_id": self.session_id,
                    "tools": tools,
                    "tools_count": len(tools),
                }
            )
        if not self.connected:
            return self._text({"error": "simulated disconnection"})
        if name == "get_head_angles":
            pose = await self.robot.status()
            return self._text({"yaw": pose.yaw, "pitch": pose.pitch})
        if name == "move_head":
            await self.robot.execute(
                RobotCommand(kind="move", yaw=arguments["yaw"], pitch=arguments["pitch"])
            )
            return self._text(
                {
                    "servo_init_ok": True,
                    "uart_num": 1,
                    "yaw_pos": 0,
                    "pitch_pos": 0,
                    "yaw_motion_started": 1,
                    "pitch_motion_started": 1,
                }
            )
        if name == "set_avatar":
            await self.robot.execute(RobotCommand(kind="emote", emotion=arguments["face"]))
            return self._text({"ok": True, "face": arguments["face"]})
        if name == "set_blink":
            self.blink = arguments["enabled"]
            return self._text({"ok": True, "enabled": self.blink})
        if name == "set_all_leds":
            self.led = tuple(arguments[c] for c in ("r", "g", "b"))
            return self._text({"available": True, "ok": True})
        if name == "get_touch_state":
            return self._text(
                {
                    "available": True,
                    "zone0": self.touch != "idle",
                    "zone1": False,
                    "zone2": False,
                    "raw": 0,
                    "last_event": self.touch,
                    "last_event_age_ms": -1 if self.touch == "idle" else 0,
                }
            )
        if name == "take_photo":
            frame = await self.robot.capture()
            with Image.open(BytesIO(frame.image)) as image:
                output = BytesIO()
                image.save(output, format="JPEG")
            data = output.getvalue()
            return [
                *self._text(
                    {
                        "image_path": "simulation-only/no-file-written.jpg",
                        "size_bytes": len(data),
                        "question": arguments["question"],
                    }
                ),
                types.ImageContent(
                    type="image", mimeType="image/jpeg", data=base64.b64encode(data).decode("ascii")
                ),
            ]
        if name == "say":
            await self.robot.execute(RobotCommand(kind="speak", speech=arguments["text"]))
            return self._text(
                {
                    "engine": "simulation",
                    "text": arguments["text"],
                    "speaker_id": None,
                    "frame_count": 0,
                    "sample_rate": 16000,
                    "frame_duration_ms": 60,
                    "duration_ms": 0,
                    "face": None,
                    "face_dispatched": False,
                    "face_error": None,
                    "face_redispatched": False,
                    "face_redispatch_error": None,
                    "text_stripped": False,
                    "spoke": True,
                }
            )
        if name == "listen":
            return self._text(
                {
                    "engine": "simulation",
                    "text": self.transcript,
                    "language": "ko",
                    "duration_ms": arguments["duration_ms"],
                    "frame_count": 0,
                    "sample_rate": 16000,
                }
            )
        return self._text({"error": "unknown simulated tool"})


@asynccontextmanager
async def simulate_mcp_robot(
    *, transcript: str = "안녕하세요", timeout_s: float = 10, history_size: int = 100
):
    """Yield a simulation adapter and close all MCP tasks on exit, including failure."""
    gateway = GatewaySimulator(transcript=transcript, history_size=history_size)
    async with create_connected_server_and_client_session(gateway.server) as session:
        # This subclass is local to the factory; arbitrary remote sessions are never accepted.
        class SimulatedAdapter(MCPRobotAdapter):
            physical = False

        adapter = SimulatedAdapter(session, timeout_s)
        adapter.gateway = gateway
        yield adapter
