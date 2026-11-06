# Loopback MCP HTTP verification

Date2026-11-06. Baseline230 tests. Final targeted HTTP23 + existing MCP56:
**79 PASS /13.80s**, using MCP1.30.0/uvicorn0.54.0/Starlette1.10.0 from uv.lock.
Whole suite after review fixes: **266 PASS /40.83s**, no failures/errors/skips on Linux.

These tests run a real TCP listener bound to127.0.0.1 on a kernel-selected port,
an actual SDK StreamableHTTP session manager and the real MCPRobotAdapter.connect.
GatewaySimulator supplies synthetic state/contracts. Only test bearer tokens are used;
the fixture is not a production authentication service or hardware gateway.

Verified cases:

- Correct/missing/wrong/revoked Authorization; unauthorized initialize is not retried.
- HTTP404 expired-session response, interrupted response body and held/stalled request.
- Gateway device/session identity pinning; old adapter faults and subsequent calls send
  no further RPC. A newly constructed connection can recover explicitly.
- Caller cancellation survives cleanup; consumer ValueError retains object identity.
- Remote adapter remains physical=True and blocks motor/capture before RPC dispatch.
- Cross-origin redirect never forwards the bearer header to another listener.
- Invalid/NaN/bool/out-of-range timeout is rejected before network I/O.
- Malformed upstream JSON cannot leak its raw body through SDK transport error logs.
  ContextVar filter applies to this connector's SDK transport contexts; unrelated client
  contexts retain their own diagnostics. Operators should keep credentials in headers.
- Client/server lifecycle leaves no extra tasks after fixture-owned SSE watcher cleanup.
- DELETE401/500 failures are observable, and trickling termination responses have an
  absolute timeout. Consumer error identity is retained with a fixed cleanup note;
  cancellation during teardown remains cancellation. A protocol-legal405 is reported
  as unsupported through a fixed warning and session_cleanup_confirmed=False.

Initial tests reproduced nested AnyIO ExceptionGroups escaping the connector. The
boundary now emits fixed MCPFailure while preserving cancellation and body errors.
It uses the current SDK streamable_http_client with explicit bounded HTTP/session
timeouts. Closed adapters remain latched. There is no command replay or automatic
creation of a replacement adapter. The SDK may reconnect its notification GET stream;
that is distinct from replaying a tool RPC.

The reviewer reproduced SDK termination swallowing HTTP500 and an inactivity timeout
being extended indefinitely by a trickling body. Six regressions failed before fixes.
The connector now owns DELETE with SDK automatic termination disabled, same-origin
redirect checks and an asyncio absolute deadline. session_cleanup_confirmed is True
for200/204, False for failed/unsupported termination, and None when there is no remote
session. This reports the protocol response, not proof of a remote physical stop.
Review corrections were verified by tests; no second review was performed.

sse-starlette maintains one intentional shutdown watcher per event loop. The test
fixture closes its own watcher by coroutine identity, without cancelling arbitrary
client tasks or changing production code. An older50ms late-effect test could time
out during catalog discovery; its1s timeout now also proves the command handler was
entered before checking that a late remote effect can outlive a local timeout.

Not verified: actual gateway token issuance/refresh/revocation implementation, TLS
certificates, external network routes, real firmware/session timing or physical effects.
The auth/session/stream fault controls simulate those server responses at the HTTP
boundary. Hardware STOP, completion ACK and privacy of a real gateway remain separate.
