# Official MCP Reconnection Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; preserve the existing
> native execution choice. Steps use checkboxes and the ignored progress ledger.

**Goal:** Recover the existing PC/GPT MCP connection without replaying paid work.
**Architecture:** Keep a single-session bridge; classify failures and supervise fresh
sessions outside it, with sequential resource cleanup. CLI adds opt-in and a Windows launcher.
**Tech Stack:** Existing Python3.11+, asyncio/AnyIO, websockets15.0.1, MCP/OpenAI SDKs; CMD.
**Spec:** [approved capability and builder defaults](../specs/2026-11-17-mcp-reconnect-design.md).

## Global Constraints

- No actual endpoint/device/paid API call, secret read, environment publication or firmware install.
- `--reconnect` defaults off; observer/reconnect combination rejected; OpenAI retry0 unchanged.
- Waits2,4,8,16,32,60, capped60; reset only after60 seconds initialized. Ctrl+C stops.
- Fatal auth/4xx/TLS/protocol/output/redirect/unknown errors stop; no replay/history transfer.
- Preserve persistent budget and all cleanup before a new session; no new dependencies.

Completion evidence: [four-platform verification and review rulings](../../validation/2026-11-17-mcp-reconnect.md).
One deferred minor deviation remains: the60s stability reset includes awaited cleanup,
so the next wait can reset early near that threshold; sequential cleanup/no replay remain.

## Review Focus

- Fatal errors hidden among temporary exception-group leaves must stop rather than loop.
- Rapid connect/close flaps must not reset delay; a genuinely stable session should reset.
- Disconnect after a paid reservation/HTTP send must not create a second automatic request.
- Cancellation during cleanup/backoff must leave no session/client tasks or later dial.
- Windows path spaces/missing config must not start networking or expose private settings.

### Task 1: Failure classification and supervisor

**Files:** modify `official_mcp.py`; create `official_mcp_runtime.py` and
`tests/test_mcp_reconnect.py`.
**Interfaces:** `BridgeError(code, *, retryable=False)` sanitizes code and allows retry
only for temporary codes. `run_reconnecting(session, *, emit, sleep, clock)` consumes
an async session callable accepting an emitter; returns after a clean session, raises
fatal error/cancellation, and otherwise opens sessions sequentially after backoff.

- [x] Write failures for missing recovery/classification, fixed negative HTTP/WS/TLS/group cases.
- [x] Run `uv run --frozen pytest -q tests/test_mcp_reconnect.py`, observe expected RED.
- [x] Implement classifier at real connection boundaries and cancellable supervisor.
- [x] Exercise real local WebSocket reconnect and malformed-session stop; run target tests GREEN.
- [x] Commit component and update ledger with exact tests and base.

### Task 2: CLI, GPT lifetime and Windows launch

**Files:** modify `official_mcp_cli.py`, `tests/test_official_mcp_cli.py`; create
`scripts/start-gpt.cmd`; extend `tests/test_mcp_reconnect.py`, installed-wheel probe
and `scripts/ci_verify.py`.
**Interfaces:** `_gpt_bridge(..., *, emit=...)` owns a fresh GPT lifecycle per call;
`_reconnecting_bridge(endpoint, settings)` runs diagnostic/GPT sessions through the supervisor.

- [x] RED: opt-in prompt-once and validation-before-input; reject observer combination.
- [x] RED: actual SDK/SQLite and real local MCP: disconnect after one paid call, reconnect
  with fresh context, old request never replayed; next fresh question increments quota once.
- [x] Implement CLI opt-in, fixed Korean guidance and single-run UTF-8 CMD launcher.
- [x] Windows-only real launcher test from unrelated cwd with missing config and no networking.
- [x] Extend installed-wheel local recovery probe; verify target/default-mode tests GREEN.
- [x] Commit; run full pytest, Ruff, package and installed probes with no external API.

### Task 3: Review, operator docs and GitHub

- [x] One fresh whole-change reviewer; one tested fix pass for important findings; ledger rulings/minors.
- [x] Update GPT/MCP launch docs, limitations, NEXT_STEPS and validation/work log.
- [x] Commit and normally FF/push existing `feat/transport-soak`; verify hosted Linux/Windows
  Python3.11/3.12 and artifact counts. No main merge, PR or environment publish.
