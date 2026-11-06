# HTTP transport and sustained mock verification

User approved the recommended device-free work: real local MCP HTTP authentication,
disconnect/reconnect validation, then sustained mock stability verification. Build on
memory42cf1a3 on a separate feature branch; do not merge the memory draft PR or publish
the cloud environment. All implementation choices here are the implementer's defaults.

## Approach

Use the installed MCP SDK's StreamableHTTP server plus uvicorn on an ephemeral
127.0.0.1 socket. An ASGI-only transport would miss socket/stream failures; a hand-built
JSON-RPC stub would miss MCP session lifecycle. Existing GatewaySimulator provides
fixture status/tools with physical execution still blocked on the remote adapter.
No new dependencies: MCP already locks uvicorn/Starlette/httpx.

Test correct/missing/incorrect bearer authorization, revoked authorization or expired
HTTP session after initialization, stalled operations, truncated response streams,
gateway identity changes and explicit manual reconnection. After uncertain failure,
latch the old adapter and send no new RPC through it. Normalize transport failures to
fixed MCPFailure without token/body leakage; preserve caller cancellation and local
consumer errors. Cleanup must close sockets/tasks, without automatic command replay.
The test server is a test utility, never a deployable gateway or auth implementation.

## Sustained verification

Add an offline-only stackchan-soak CLI using the actual engine, FakeRobotAdapter,
MockDecisionProvider and isolated temporary SQLite files. Ignore application env/.env
for this harness so it cannot select a device, paid API, or a user's DB. Drive mixed
timer/person/touch/voice fixture events; periodically close/recreate the engine and
verify retained metadata/preferences. Measure warmed Python traced-heap growth,
task counts, bounded histories and cleanup; report numeric metadata only.

Support bounded cycle-count and monotonic real-duration runs, optional pacing and an
explicit virtual clock step. Distinguish real wall elapsed from virtual elapsed in
every report. Fail on bounds/errors/insufficient measurement and exit nonzero; do not
convert interruption into PASS. A JSON report may be saved under .local and uploaded
as metadata in CI. No dialogue, raw media, credentials, DB or process environment.

This task will run a real paced10-minute soak plus a separate accelerated24-hour
virtual scenario. Neither proves24-hour real elapsed operation or physical reliability.
Provide a24-hour real-duration command for the user's PC; do not claim it was run.

## Completion evidence

Targeted regressions first, full suite, lint/build/independent installed entry-point
checks, fresh read-only review and Windows/Linux Python3.11/3.12 CI on the feature branch.
Keep remote physical/media guards, explicit cloud consent and existing lease/quota policy.
