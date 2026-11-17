"""Installed transport recovery through local real WebSockets/MCP; no paid API."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import stackchan_autonomy.official_mcp as bridge
from stackchan_autonomy.official_mcp_runtime import run_reconnecting

ENDPOINT = "wss://api.xiaozhi.me/mcp/?token=synthetic-wheel-recovery"


async def main():
    result = asyncio.get_running_loop().create_future()
    sessions, lines = [], []

    async def peer(socket):
        try:
            sessions.append(1)

            async def rpc(number, method, params):
                await socket.send(
                    json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
                )
                return json.loads(await socket.recv())

            await rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "wheel-recovery", "version": "1"},
                },
            )
            await socket.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            listing = await rpc(2, "tools/list", {})
            assert len(listing["result"]["tools"]) == 2
            status = await rpc(
                3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
            )
            assert status["result"]["structuredContent"]["call_count"] == 1
            if len(sessions) == 1:
                await socket.close()
            else:
                result.set_result(status)
                await socket.wait_closed()
        except Exception as error:
            if not result.done():
                result.set_exception(error)

    async with serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        @asynccontextmanager
        async def local_only(uri, **kwargs):
            assert uri == ENDPOINT
            async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                yield socket

        original = bridge.connect
        bridge.connect = local_only

        async def session(emit):
            await bridge.run_bridge(ENDPOINT, emit=emit)

        async def no_wall_wait(seconds):
            assert seconds == 2

        task = asyncio.create_task(run_reconnecting(session, emit=lines.append, sleep=no_wall_wait))
        try:
            await asyncio.wait_for(result, 10)
            assert len(sessions) == 2 and lines.count("OFFICIAL_MCP_INITIALIZED") == 2
            assert lines.count("PC_TOOL_CALLED=1") == 2
            assert "OFFICIAL_MCP_RECONNECT_WAIT=2" in lines
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            bridge.connect = original
    print("Installed MCP recovery / fresh local sessions: PASS")


if __name__ == "__main__":
    asyncio.run(main())
