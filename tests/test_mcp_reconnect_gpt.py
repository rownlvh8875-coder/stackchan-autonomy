"""Real MCP/SDK cancellation and persistent quota across transport reconnects."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from test_gpt_chat import response_payload, settings
from test_official_mcp import ENDPOINT, bridge_module, initialize, request

from stackchan_autonomy import gpt_chat, official_mcp_cli
from stackchan_autonomy.official_mcp_runtime import run_reconnecting


async def test_disconnect_during_paid_call_closes_old_client_and_never_replays(
    monkeypatch, tmp_path
):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    started, api_cancelled = asyncio.Event(), asyncio.Event()
    result = asyncio.get_running_loop().create_future()
    posted, chats, peers, lines = [], [], [], []
    original = gpt_chat.GPTChat

    async def api(req):
        payload = json.loads(req.content)
        posted.append(payload)
        if len(posted) == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                api_cancelled.set()
                raise
        return httpx.Response(200, json=response_payload("다시 연결됐습니다."))

    def client_factory(config):
        client = AsyncOpenAI(
            api_key="synthetic-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)),
        )
        chat = original(config, client=client)
        chats.append(chat)
        return chat

    monkeypatch.setattr(gpt_chat, "GPTChat", client_factory)

    async def peer(socket):
        try:
            peers.append(1)
            await initialize(socket)
            await request(socket, 2, "tools/list", {})
            if len(peers) == 1:
                await socket.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {
                                "name": "stackchan_gpt_reply",
                                "arguments": {"question": "PRIVATE-OLD"},
                            },
                        }
                    )
                )
                await started.wait()
                await socket.close()
            else:
                await asyncio.sleep(0.05)
                assert len(posted) == 1 and api_cancelled.is_set()
                assert chats[0].client.is_closed() and chats[0]._history == []
                assert chats[1].budget.snapshot().requests == 1
                answer = await request(
                    socket,
                    3,
                    "tools/call",
                    {"name": "stackchan_gpt_reply", "arguments": {"question": "PRIVATE-NEW"}},
                )
                result.set_result(answer)
                await socket.wait_closed()
        except Exception as error:
            if not result.done():
                result.set_exception(error)

    module = bridge_module()
    async with serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        @asynccontextmanager
        async def local_only(uri, **kwargs):
            assert uri == ENDPOINT
            async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                yield socket

        monkeypatch.setattr(module, "connect", local_only)

        async def fast_sleep(seconds):
            assert seconds == 2
            assert chats[-1].client.is_closed()

        async def supervise(session, *, emit):
            await run_reconnecting(session, emit=emit, sleep=fast_sleep)

        monkeypatch.setattr(official_mcp_cli, "run_reconnecting", supervise, raising=False)
        monkeypatch.setattr(official_mcp_cli, "_reconnect_status", lines.append, raising=False)
        task = asyncio.create_task(
            official_mcp_cli._reconnecting_bridge(
                ENDPOINT, settings(tmp_path, requests_per_minute=60)
            )
        )
        try:
            answer = await asyncio.wait_for(result, 5)
            assert answer["result"]["structuredContent"]["answer"] == "다시 연결됐습니다."
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert len(posted) == 2 and len(chats) == 2
    assert posted[0]["input"] == [{"role": "user", "content": "PRIVATE-OLD"}]
    assert posted[1]["input"] == [{"role": "user", "content": "PRIVATE-NEW"}]
    assert all(chat.client.is_closed() and not chat._storage.pending for chat in chats)
    assert chats[-1].budget.snapshot().requests == 2
    assert "PRIVATE-OLD" not in str(lines) and "PRIVATE-NEW" not in str(lines)
