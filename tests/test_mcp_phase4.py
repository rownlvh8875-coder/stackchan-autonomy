import asyncio
import base64
import copy
import json
from contextlib import asynccontextmanager
from importlib.resources import files
from io import BytesIO

import pytest
from mcp import types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session
from PIL import Image

from stackchan_autonomy.mcp_robot import MCPRobotAdapter
from stackchan_autonomy.models import Event, EventKind, RobotCommand
from stackchan_autonomy.simulation import simulate_mcp_robot

DEVICE_TOOLS = [
    "self.robot.get_head_angles",
    "self.robot.set_head_angles",
    "self.camera.take_photo",
    "self.display.set_avatar",
    "self.display.set_blink",
    "self.led.set_all",
    "self.touch.get_touch_state",
]


@asynccontextmanager
async def fixture_gateway(*, pose=None, status=None, schemas=None):
    """Independent replies for malformed gateway boundaries; no physical connection."""
    server = Server("independent-fixture")
    captured = json.loads(
        files("stackchan_autonomy")
        .joinpath("data/upstream_mcp_tools.json")
        .read_text(encoding="utf-8")
    )["tools"]
    state = {
        "status": status
        if status is not None
        else {
            "connected": True,
            "initialized": True,
            "device_id": "robot-a",
            "session_id": "session-a",
            "tools_count": len(DEVICE_TOOLS),
            "tools": DEVICE_TOOLS,
        },
        "pose": pose if pose is not None else {"yaw": 12, "pitch": 41},
        "schemas": copy.deepcopy(captured if schemas is None else schemas),
        "calls": [],
        "overrides": {},
    }

    @server.list_tools()
    async def list_tools():
        return [types.Tool(**tool) for tool in state["schemas"]]

    @server.call_tool()
    async def call_tool(name, arguments):
        state["calls"].append((name, arguments))
        if name in state["overrides"]:
            return state["overrides"][name]
        data = state["status"] if name == "get_status" else state["pose"]
        return [types.TextContent(type="text", text=json.dumps(data))]

    async with create_connected_server_and_client_session(server) as session:
        yield MCPRobotAdapter(session), state


async def test_readonly_status_uses_real_pose_instead_of_neutral_defaults():
    async with fixture_gateway() as (adapter, state):
        result = await adapter.status()
        assert (result.yaw, result.pitch) == (12, 41)
        assert result.connected
        assert adapter.physical
        assert {name for name, _ in state["calls"]} <= {"get_status", "get_head_angles"}


@pytest.mark.parametrize(
    "pose",
    [
        {"yaw": None, "pitch": None, "error": "private bus details"},
        {"yaw": True, "pitch": 45},
        {"yaw": "0", "pitch": 45},
        {"yaw": 0, "pitch": float("nan")},
        {"yaw": 91, "pitch": 45},
        {"yaw": 0, "pitch": 0},
        {"yaw": 0},
        [],
        None,
    ],
)
async def test_invalid_pose_latches_fault_without_fabricating_position(pose):
    async with fixture_gateway() as (adapter, state):
        state["pose"] = pose
        with pytest.raises(ConnectionError):
            await adapter.status()
        calls = len(state["calls"])
        with pytest.raises(ConnectionError):
            await adapter.status()
        assert len(state["calls"]) == calls
        assert adapter.faulted


@pytest.mark.parametrize(
    "key,value", [("session_id", "session-b"), ("device_id", "robot-b"), ("connected", False)]
)
async def test_identity_or_connection_change_requires_manual_recovery(key, value):
    async with fixture_gateway() as (adapter, state):
        await adapter.status()
        state["status"][key] = value
        with pytest.raises(ConnectionError):
            await adapter.status()
        assert adapter.faulted


@pytest.mark.parametrize(
    "mutation",
    ["missing_required", "wrong_type", "wrong_range", "missing_low_speed", "extra_required"],
)
async def test_changed_motor_schema_disables_motor_capability(mutation):
    async with fixture_gateway() as (adapter, state):
        schema = next(t["inputSchema"] for t in state["schemas"] if t["name"] == "move_head")
        if mutation == "missing_required":
            schema["required"] = ["yaw"]
        elif mutation == "wrong_type":
            schema["properties"]["yaw"]["type"] = "string"
        elif mutation == "wrong_range":
            schema["properties"]["pitch"]["minimum"] = 0
        elif mutation == "missing_low_speed":
            schema["properties"]["speed"] = {"enum": ["fast"]}
        else:
            schema["required"].append("unknown_option")
        report = await adapter.discover()
        assert "move" not in report.available


async def test_real_adapter_blocks_all_actuation_and_capture_before_rpc():
    async with fixture_gateway() as (adapter, state):
        for operation in [
            adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45)),
            adapter.capture(),
            adapter.set_blink(True),
            adapter.set_all_leds(1, 2, 3),
            adapter.listen(),
        ]:
            with pytest.raises(PermissionError):
                await operation
        assert state["calls"] == []


async def test_simulation_exercises_actual_mcp_methods_and_absolute_quantized_targets():
    async with simulate_mcp_robot() as adapter:
        assert not adapter.physical
        await adapter.execute(RobotCommand(kind="move", yaw=10.4, pitch=49.6))
        pose = await adapter.status()
        assert (pose.yaw, pose.pitch) == (10, 50)
        motor = [args for name, args in adapter.gateway.calls if name == "move_head"]
        assert motor == [{"yaw": 10, "pitch": 50, "speed": "low"}]
        await adapter.execute(RobotCommand(kind="emote", emotion="happy"))
        await adapter.set_blink(True)
        await adapter.set_all_leds(10, 20, 30)
        assert adapter.gateway.robot.emotion == "happy"
        assert adapter.gateway.led == (10, 20, 30)
        assert adapter.gateway.blink


@pytest.mark.parametrize(
    "command",
    [
        RobotCommand(kind="move", yaw=16, pitch=45),
        RobotCommand(kind="move", yaw=0, pitch=0),
        RobotCommand(kind="move", yaw=0, pitch=86),
        RobotCommand(kind="emote", emotion="off"),
        RobotCommand(kind="speak", speech=""),
        RobotCommand(kind="emote", emotion="happy", speech="hidden compound"),
    ],
)
async def test_mcp_boundary_rechecks_unsafe_direct_commands(command):
    async with simulate_mcp_robot() as adapter:
        with pytest.raises(ValueError):
            await adapter.execute(command)
        assert not adapter.gateway.robot.history


async def test_simulated_inline_photo_is_jpeg_and_does_not_read_receipt_path():
    async with simulate_mcp_robot() as adapter:
        frame = await adapter.capture()
        assert frame.image_mime == "image/jpeg"
        assert Image.open(BytesIO(frame.image)).format == "JPEG"
        assert frame.person_present is None  # No fabricated CV result over real protocol.
        calls = [args for name, args in adapter.gateway.calls if name == "take_photo"]
        assert len(calls) == 1 and calls[0]["question"]


@pytest.mark.parametrize(
    "case", ["path_only", "bad_base64", "not_jpeg", "is_error", "json_error", "missing_servo_ack"]
)
async def test_bad_gateway_replies_fault_without_replay(case, caplog):
    async with simulate_mcp_robot() as adapter:
        if case == "missing_servo_ack":
            adapter.gateway.responses["move_head"] = [types.TextContent(type="text", text="{}")]

            async def operation():
                await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        else:
            text = types.TextContent(type="text", text='{"image_path":"/private/do-not-read.jpg"}')
            image = types.ImageContent(
                type="image",
                mimeType="image/jpeg",
                data=("%%%" if case == "bad_base64" else base64.b64encode(b"not a jpeg").decode()),
            )
            content = [text] if case == "path_only" else [text, image]
            if case == "json_error":
                content = [
                    types.TextContent(type="text", text='{"error":"secret-private-details"}')
                ]
            adapter.gateway.responses["take_photo"] = types.CallToolResult(
                content=content, isError=case == "is_error"
            )
            operation = adapter.capture
        with pytest.raises(ConnectionError):
            await operation()
        count = len(adapter.gateway.calls)
        with pytest.raises(ConnectionError):
            await operation()
        assert len(adapter.gateway.calls) == count
        assert adapter.faulted
    assert "secret-private-details" not in caplog.text


async def test_touch_unavailable_is_not_a_fabricated_user_event():
    async with simulate_mcp_robot() as adapter:
        adapter.gateway.responses["get_touch_state"] = [
            types.TextContent(
                type="text",
                text=(
                    '{"available":false,"zone0":false,"zone1":false,"zone2":false,'
                    '"raw":0,"last_event":"idle","last_event_age_ms":-1}'
                ),
            )
        ]
        assert await adapter.touch_state() is None
        assert not adapter.faulted


async def test_touch_and_listen_are_simulated_without_recording_or_private_logs(caplog):
    async with simulate_mcp_robot(transcript="안녕") as adapter:
        adapter.gateway.touch = "tap"
        touch = await adapter.touch_state()
        assert touch.last_event == "tap"
        event = await adapter.listen(duration_ms=100)
        assert event.kind == EventKind.VOICE_REQUEST
        assert event.text == "안녕"
        request = next(args for name, args in adapter.gateway.calls if name == "listen")
        assert request == {"duration_ms": 100, "language": "ko", "motion": "none"}
    assert "안녕" not in caplog.text


async def test_mcp_simulation_runs_engine_without_cloud_or_real_device():
    from stackchan_autonomy.decision import MockDecisionProvider
    from stackchan_autonomy.engine import AutonomyEngine
    from stackchan_autonomy.settings import Settings

    async with simulate_mcp_robot() as adapter:
        engine = AutonomyEngine(adapter, MockDecisionProvider(), Settings(cooldown_s=0))
        try:
            result = await engine.step(Event(kind=EventKind.TOUCH_TAP))
            assert result.executed
            assert [c.kind for c in adapter.gateway.robot.history] == ["speak"]
        finally:
            await engine.aclose()


async def test_simulated_command_timeout_latches_fault_without_replay():
    async with simulate_mcp_robot(timeout_s=0.05) as adapter:
        entered = asyncio.Event()

        async def stalled(arguments):
            entered.set()
            await asyncio.Event().wait()

        adapter.gateway.responses["move_head"] = stalled
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert entered.is_set()
        assert adapter.faulted
        assert not adapter.gateway.robot.history


async def test_simulation_direct_calls_have_single_owner_and_slew_validation():
    async with simulate_mcp_robot() as adapter:
        await asyncio.gather(
            adapter.execute(RobotCommand(kind="move", yaw=10, pitch=45)),
            adapter.execute(RobotCommand(kind="move", yaw=20, pitch=45)),
        )
        assert [c.yaw for c in adapter.gateway.robot.history] == [10, 20]


async def test_schema_change_between_discovery_and_command_disables_dispatch():
    async with simulate_mcp_robot() as adapter:
        assert "move" in (await adapter.discover()).available
        schema = next(t["inputSchema"] for t in adapter.gateway.schemas if t["name"] == "move_head")
        schema["required"].append("unsupported")
        with pytest.raises(ValueError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert not adapter.gateway.robot.history


async def test_post_ack_session_change_faults_and_never_replays():
    async with simulate_mcp_robot() as adapter:

        async def changed_session(arguments):
            adapter.gateway.session_id = "replacement-session"
            return [types.TextContent(type="text", text='{"servo_init_ok":true}')]

        adapter.gateway.responses["move_head"] = changed_session
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        calls = len(adapter.gateway.calls)
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert len(adapter.gateway.calls) == calls
        assert adapter.faulted


async def test_cancelled_mcp_command_blocks_queued_write_and_leaves_no_tasks():
    baseline = len(asyncio.all_tasks())
    async with simulate_mcp_robot() as adapter:
        entered = asyncio.Event()

        async def wait_for_cancel(arguments):
            entered.set()
            await asyncio.Event().wait()

        adapter.gateway.responses["move_head"] = wait_for_cancel
        first = asyncio.create_task(adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45)))
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(adapter.set_blink(False))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ConnectionError):
            await second
        assert not [name for name, _ in adapter.gateway.calls if name == "set_blink"]
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) <= baseline


async def test_simulation_cannot_rebind_itself_to_a_remote_session(monkeypatch):
    from stackchan_autonomy import mcp_robot

    @asynccontextmanager
    async def local_transport(*args, **kwargs):
        yield (None, None, None)

    class LocalSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

    async with simulate_mcp_robot() as simulated:
        monkeypatch.setattr(mcp_robot, "streamablehttp_client", local_transport)
        monkeypatch.setattr(mcp_robot, "ClientSession", LocalSession)
        async with simulated.connect("https://example.invalid/mcp") as connected:
            assert connected.physical
            with pytest.raises(PermissionError):
                await connected.execute(RobotCommand(kind="move", yaw=5, pitch=45))


async def test_sdk_reply_validation_failure_latches_fault_before_any_next_request(monkeypatch):
    async with simulate_mcp_robot() as adapter:
        original = adapter.session.call_tool

        async def malformed_response(name, arguments):
            if name == "move_head":
                # This is the Pydantic decode error real ClientSession raises on bad JSON-RPC data.
                types.CallToolResult.model_validate({"content": 123})
            return await original(name, arguments)

        monkeypatch.setattr(adapter.session, "call_tool", malformed_response)
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        count = len(adapter.gateway.calls)
        with pytest.raises(ConnectionError):
            await adapter.set_blink(False)
        assert len(adapter.gateway.calls) == count
        assert adapter.faulted


@pytest.mark.parametrize("constraint", ["not", "const", "enum", "allOf"])
async def test_unmodeled_schema_constraints_disable_motor(constraint):
    async with simulate_mcp_robot() as adapter:
        schema = next(t["inputSchema"] for t in adapter.gateway.schemas if t["name"] == "move_head")
        if constraint in {"not", "allOf"}:
            schema[constraint] = {} if constraint == "not" else [{"required": ["unsupported"]}]
        else:
            schema["properties"]["yaw"][constraint] = 0 if constraint == "const" else [0]
        assert "move" not in (await adapter.discover()).available


@pytest.mark.parametrize(
    "ack",
    [
        {"servo_init_ok": True},
        {
            "servo_init_ok": True,
            "uart_num": 1,
            "yaw_pos": 460,
            "pitch_pos": 620,
            "yaw_motion_started": 0,
            "pitch_motion_started": 0,
        },
        {
            "servo_init_ok": True,
            "uart_num": 1,
            "yaw_pos": -1,
            "pitch_pos": 620,
            "yaw_motion_started": 1,
            "pitch_motion_started": 0,
        },
    ],
)
async def test_initialization_flag_alone_is_not_a_motor_dispatch_ack(ack):
    async with simulate_mcp_robot() as adapter:
        adapter.gateway.responses["move_head"] = [
            types.TextContent(type="text", text=json.dumps(ack))
        ]
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert adapter.faulted


async def test_timeout_does_not_imply_remote_rollback():
    async with simulate_mcp_robot(timeout_s=1) as adapter:
        release, applied, entered = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def late_command(arguments):
            entered.set()
            await release.wait()
            await adapter.gateway.robot.execute(RobotCommand(kind="move", yaw=5, pitch=45))
            applied.set()
            return [types.TextContent(type="text", text='{"servo_init_ok":true}')]

        adapter.gateway.responses["move_head"] = late_command
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert entered.is_set()  # Establish dispatch before interpreting the timeout.
        release.set()
        await asyncio.wait_for(applied.wait(), 1)
        with pytest.raises(ConnectionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        assert len([name for name, _ in adapter.gateway.calls if name == "move_head"]) == 1
        assert len(adapter.gateway.robot.history) == 1


@pytest.mark.parametrize("marker", [{"ok": 0}, {"ok": "true"}, {"error": ""}, {"available": 0}])
async def test_malformed_success_markers_cannot_validate_pose(marker):
    async with fixture_gateway(pose={"yaw": 0, "pitch": 45, **marker}) as (adapter, _):
        with pytest.raises(ConnectionError):
            await adapter.status()
        assert adapter.faulted


async def test_already_reached_absolute_motor_target_is_not_resent():
    async with simulate_mcp_robot() as adapter:
        await adapter.execute(RobotCommand(kind="move", yaw=0, pitch=45))
        assert not [name for name, _ in adapter.gateway.calls if name == "move_head"]
