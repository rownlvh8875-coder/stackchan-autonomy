"""Test-only real loopback MCP server. No production auth or device integration."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager, contextmanager

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sse_starlette.sse import _shutdown_watcher
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from stackchan_autonomy.simulation import GatewaySimulator


class HTTPGateway:
    token = "fixture-token-never-log"

    def __init__(self):
        self.gateway = GatewaySimulator()
        self.authorized = True
        self.post_attempts = 0
        self.rpc = []
        self.fault = None
        self.redirect_url = None
        self.stall_entered = asyncio.Event()
        self.delete_status = None
        self.trickle_delete = False
        self.delete_entered = asyncio.Event()
        self.manager = StreamableHTTPSessionManager(
            app=self.gateway.server,
            json_response=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*"],
                allowed_origins=["http://127.0.0.1:*"],
            ),
        )

        @asynccontextmanager
        async def lifespan(app):
            async with self.manager.run():
                yield

        self.app = Starlette(
            routes=[Route("/mcp", self, methods=["POST", "GET", "DELETE"])],
            lifespan=lifespan,
        )

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    async def __call__(self, scope, receive, send):
        if scope["method"] == "POST":
            self.post_attempts += 1
        headers = dict(scope["headers"])
        if not self.authorized or headers.get(b"authorization") != f"Bearer {self.token}".encode():
            await Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})(
                scope, receive, send
            )
            return
        if scope["method"] == "DELETE":
            self.delete_entered.set()
            if self.delete_status is not None:
                await Response("private-cleanup-response", status_code=self.delete_status)(
                    scope, receive, send
                )
                return
            if self.trickle_delete:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-length", b"100")],
                    }
                )
                for index in range(100):
                    await asyncio.sleep(0.05)
                    await send(
                        {"type": "http.response.body", "body": b"x", "more_body": index < 99}
                    )
                return
        if scope["method"] == "POST":
            chunks = []
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            payload = json.loads(body)
            method = payload.get("method")
            tool = payload.get("params", {}).get("name")
            self.rpc.append((method, tool))
            pending = True
            original_receive = receive

            async def replay_receive():
                nonlocal pending
                if pending:
                    pending = False
                    return {"type": "http.request", "body": body, "more_body": False}
                return await original_receive()

            receive = replay_receive
            if method == "tools/call" and tool == "get_head_angles" and self.fault:
                fault, self.fault = self.fault, None
                if fault == "expired":
                    await Response(status_code=404)(scope, receive, send)
                    return
                if fault == "bad_json":
                    await Response(
                        '{"private_response":"private-upstream-content"}',
                        media_type="application/json",
                    )(scope, receive, send)
                    return
                if fault == "redirect":
                    await Response(status_code=307, headers={"Location": self.redirect_url})(
                        scope, receive, send
                    )
                    return
                if fault == "drop":
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", b"10000"),
                            ],
                        }
                    )
                    await send(
                        {"type": "http.response.body", "body": b'{"jsonrpc":', "more_body": True}
                    )
                    raise RuntimeError("intentional fixture stream interruption")
                if fault == "stall":
                    self.stall_entered.set()
                    # HTTP disconnect/cancellation ends the held request without delayed work.
                    while (await receive())["type"] != "http.disconnect":
                        pass
                    return
        await self.manager.handle_request(scope, receive, send)


class QuietServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


@asynccontextmanager
async def running_gateway():
    tasks_before = asyncio.all_tasks()
    service = HTTPGateway()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.setblocking(False)
    service.url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    server = QuietServer(
        uvicorn.Config(
            service.app,
            host="127.0.0.1",
            port=0,
            log_level="critical",
            access_log=False,
            lifespan="on",
            timeout_graceful_shutdown=0.5,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]), name="fixture-http-server")
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("fixture server did not start")
                await asyncio.sleep(0.005)
        yield service
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 3)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            sock.close()
            # sse-starlette intentionally owns one watcher per loop, not per response.
            # This fixture owns its startup side effect; do not hide client task leaks.
            watchers = [
                pending
                for pending in asyncio.all_tasks() - tasks_before
                if getattr(pending.get_coro(), "cr_code", None) is _shutdown_watcher.__code__
            ]
            for pending in watchers:
                pending.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)
