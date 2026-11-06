import json
import os
import subprocess
import sys

import pytest
from mcp import types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session

from stackchan_autonomy.mcp_robot import MCPRobotAdapter
from stackchan_autonomy.models import RobotCommand


def test_cli_mock_runs_without_api_key_and_reports_only_metadata():
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy", "--cycles", "3", "--person"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["mode"] == "mock"
    assert summary["cycles"] == 3
    assert summary["simulated_actions"] == 1
    assert summary["cloud_requests"] == 0
    assert "speech" not in result.stdout


def test_cli_does_not_accept_hardware_mode():
    result = subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy", "--mode", "hardware"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2


def test_cli_mcp_simulation_is_offline_and_retains_no_cloud_requests():
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "stackchan_autonomy",
            "--mode",
            "mcp-sim",
            "--cycles",
            "3",
            "--event",
            "touch",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary == {
        "mode": "mcp-sim",
        "robot": "mcp-simulated",
        "cycles": 3,
        "state": "IDLE",
        "simulated_actions": 1,
        "cloud_requests": 0,
    }


async def test_mcp_real_sdk_discovery_intersects_firmware_and_gateway_capabilities():
    server = Server("fixture-gateway")
    called = []

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(name="get_status", inputSchema={"type": "object", "properties": {}}),
            types.Tool(
                name="move_head",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "yaw": {"type": "integer", "minimum": -90, "maximum": 90},
                        "pitch": {"type": "integer", "minimum": 5, "maximum": 85},
                        "speed": {"enum": ["low", "mid", "high"]},
                    },
                    "required": ["yaw", "pitch"],
                },
            ),
            types.Tool(
                name="set_avatar",
                inputSchema={
                    "type": "object",
                    "properties": {"face": {"type": "string", "enum": ["idle", "happy"]}},
                    "required": ["face"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        called.append(name)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "connected": True,
                        "tools": ["self.robot.set_head_angles"],
                        "tools_count": 1,
                        "initialized": True,
                        "session_id": "test-session",
                        "device_id": "test",
                    }
                ),
            )
        ]

    async with create_connected_server_and_client_session(server) as session:
        adapter = MCPRobotAdapter(session)
        report = await adapter.discover()
        assert report.connected
        assert "move" in report.available
        assert "emote" not in report.available
        assert not report.physical_execution_enabled
        with pytest.raises(PermissionError):
            await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
        with pytest.raises(PermissionError):
            await adapter.capture()
    assert called == ["get_status"]


async def test_mcp_error_payload_and_unknown_schema_fail_closed():
    server = Server("error-gateway")

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name="get_status", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name, arguments):
        return [types.TextContent(type="text", text='{"error":"not connected"}')]

    async with create_connected_server_and_client_session(server) as session:
        report = await MCPRobotAdapter(session).discover()
        assert not report.connected
        assert not report.available
