# Official MCP reconnection and Windows launch

User approved the capability brief with “그래 진행해”: reconnect the PC transport,
never replay GPT questions, simplify Windows launch and explain missing configuration.
Implement inline using the existing execution choice. The concrete defaults below
are builder decisions within that approval, not additional user-supplied requirements.

## Approach and boundaries

Keep `run_bridge` a single MCP session and put optional recovery in a supervisor.
Reconnecting inside its receiver would reuse SDK/request state; restarting a shell
would repeatedly prompt for the endpoint and make cancellation/cleanup harder.
The supervisor instead starts a new session only after the prior one has unwound.

Add `--reconnect`, default off for compatibility. It works with diagnostics or `--gpt`.
Reject combining it with experimental `--observer-port`: USB snapshots and physical
reopens are outside this text-transport recovery scope. No firmware/device/API calls
during development, environment publication, credential persistence or OS startup task.

## Recovery contract

- Retry only classified temporary connection/timeout/remote-close failures. Unknown
  internal failures are fatal. Protocol/output/redirection/validation errors are fatal.
- HTTP401/403/proxy407 are authentication failures; other4xx handshakes, including429,
  stop. Do not hammer a rate-limited endpoint or follow a redirect.5xx are temporary.
  Certificate/SSL verification failures stop; TLS remains verified.
- WebSocket close1000/1001/1005/1006/1011/1012/1013 are recoverable. Policy/protocol/data-size
  rejection closes stop. Exception groups containing a fatal leaf must stop.
- Retry waits2,4,8,16,32,60 seconds then stay60, until stopped. Reset to2 only after
 60 seconds of initialized operation, so short flaps cannot create a rapid dial loop.
  Sleep is asynchronous and cancellable; Ctrl+C exits130, with no new dial afterward.
- New SDK server/request queues/check code per connection. Hidden endpoint input once
  per process, held in memory only. No question/answer/tool-result replay or reconnect
  transcript. Existing OpenAI retry0 and persistent quota remain in force.
- New GPT object per session: close/drain its client/storage before any next session;
  clear RAM dialogue on close, reuse the same configured persistent budget database.
  A request sent before disconnect may be charged without an audible answer. A truly
  new server tool call is a new request; distributed exactly-once billing is not promised.

## Operator interface

Keep fixed ASCII lifecycle markers. Add RECONNECT_WAIT=<seconds> and RECONNECTING=<n>;
only fixed/sanitized error codes, never URL, key, dialogue, remote reason or device IDs.
Reconnect mode also shows short Korean connection/configuration guidance.

`scripts/start-gpt.cmd` locates uv in the user's local bin or PATH, changes to the
repository via its own directory, uses UTF-8 and runs `--gpt --reconnect` once. It
does not shell-loop, write configuration/secrets, install drivers or schedule startup.
Fatal errors remain visible; Ctrl+C does not restart. Existing local `.env` is used.

## Evidence

TDD for classifier/supervisor: transient→ready, auth/TLS/protocol/rate-limit fatal,
fatal wins in groups, bounded backoff and stable reset, cancellation/cleanup and output
failure. Local real WebSockets/MCP sessions plus actual Responses SDK MockTransport
prove a disconnected in-flight call is not replayed and persistent quota survives.
CLI validates before prompting, asks endpoint once, keeps old single-session behavior,
rejects observer recovery; Windows launcher runs from another directory with config
failure and no network. Installed-wheel probe exercises reconnect outside source.
Run full suite/lint/package and Windows/Linux CI, one fresh whole-change review.
Physical robot/actual internet outage/paid API acceptance remains a later operator check.
