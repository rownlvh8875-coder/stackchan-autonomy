# Official MCP PC Connection Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the existing official AI call one read-only PC connection-check tool while preserving factory firmware and the mobile app.

**Architecture:** A standalone Windows-friendly CLI runs an MCP SDK server over one outbound authenticated WebSocket. A per-run code and invocation count distinguish real PC tool calls from an AI answer without a tool call. No robot adapter, media, file/command tool or OpenAI provider is loaded.

**Tech Stack:** Python >=3.11, pinned MCP1.30.0/AnyIO, websockets15.0.1, pytest/pytest-asyncio, uv locked packaging.

**Spec:** [Approved design](../specs/2026-11-16-official-mcp-pc-bridge-design.md).

## Global Constraints

- Preserve K151 V1.6.2 and StackChan World; existing physical execution blocks remain.
- One tool `stackchan_pc_connection_status`, no arguments, strict rejection of extra arguments.
- Only official TLS endpoint api.xiaozhi.me:443, /mcp or /mcp/, one nonempty token query, no userinfo/fragment/extra query fields.
- Input16KiB, output64KiB, bounded16-message queues/pending requests and one active tool call.
- Connection establishment10s; initialization30s; normal initialized session idles until cancellation/disconnect.
- No automatic reconnect or replay; no real user token, robot or paid API in cloud testing.
- Fixed lifecycle/error outputs only; no raw URL/messages/errors, tokens, traceback or host identifiers.
- Configuration error2, network/protocol failure1, Ctrl+C130, help0.
- Use existing feature-branch authorization for final normal push; no merge/PR/environment publication.

## Review Focus

- A copied URL containing whitespace, disguised authority, duplicate token or unexpected query must fail locally without leaking its value.
- A backend connects but never initializes: terminate on the initialization deadline and close every task/socket.
- An endpoint sends many unanswered requests/notifications: bounds must apply to actual SDK work, not only an easily drained transport queue.
- Closing/canceling during reader/writer failure must promptly clean up and cannot trigger reconnect or a second tool call.
- SDK/WebSocket exception text or logging may contain an endpoint/secret: no such material may reach console or captured logs.

## File map

- `src/stackchan_autonomy/official_mcp.py`: endpoint validation, one tool, bounded SDK/WebSocket session.
- `src/stackchan_autonomy/official_mcp_cli.py`: secret input, output/exit contract and standalone entry point.
- `tests/test_official_mcp.py`, `tests/test_official_mcp_cli.py`: real local protocol and boundary/CLI checks.
- `pyproject.toml`, `uv.lock`: direct pinned WebSocket dependency and console entry point.
- `scripts/ci_verify.py`: independent installed-wheel bridge import/entry verification.
- `docs/OFFICIAL_MCP_PC.ko.md`, README/runbook/next steps/test report/work log: operator flow and evidence.

### Task 1: Bounded read-only official MCP bridge

**Files:** Create `official_mcp.py`, `tests/test_official_mcp.py`; modify dependency files.

**Interfaces:**
- Produces `validate_endpoint(value: str) -> str`: trim outer whitespace, validate without exporting input; return validated URI.
- Produces `BridgeError` with a fixed public `code`, never an underlying exception message.
- Produces `async run_bridge(endpoint: str, *, emit: Callable[[str], None]) -> None`.
- Emits fixed lifecycle lines and one per-run six-digit code; tool calls reuse code and increment count.

- [x] Write RED tests: invalid URL variants/secret-free failures; a real local WebSocket endpoint initializes the real SDK, lists exactly one no-argument tool and calls twice, verifying stable code/incremented count/no robot capability.
- [x] Run `.venv/bin/python -m pytest tests/test_official_mcp.py -q`; expect failures because bridge/API is missing, not unrelated fixture failures.
- [x] Add websockets15.0.1 through uv and implement the minimal SDK server/transport with the above interfaces. Use test-only monkeypatching of the outbound connection target to keep CLI production endpoint validation intact.
- [x] Add RED cases for pre-initialization calls, extra/unknown tool arguments, bad JSON/binary/oversized frames, invalid order, initialization stall, bounded flooding, disconnect and cancellation cleanup; observe each failing before fixing it.
- [x] Ensure request admission bounds SDK work itself; fixed errors/privacy-safe library logging. Status response has only service, check_code, uptime_s, call_count and robot_control_available=false.
- [x] Run target tests and Ruff checks; expect all pass. Commit core/dependency/tests as one deliverable.

### Task 2: Secret-safe Windows CLI, packaging and operator handoff

**Files:** Create `official_mcp_cli.py`, `tests/test_official_mcp_cli.py`, `docs/OFFICIAL_MCP_PC.ko.md`; modify console entry point, `scripts/ci_verify.py` and linked docs.

**Interfaces:**
- Consumes Task1 `validate_endpoint`, `run_bridge`, `BridgeError`.
- Produces `main(argv: list[str] | None = None) -> int` and console `stackchan-pc-mcp`.
- Default hidden console prompt; optional `STACKCHAN_OFFICIAL_MCP_ENDPOINT` env input is never echoed/persisted. No URL CLI argument or TLS/host bypass flag.

- [x] Write and run RED CLI behavior tests: config rejection without network/secret output, missing non-TTY input fails without getpass echo fallback, help0, fixed network failure1 and KeyboardInterrupt130; env ignores app .env/engine configuration.
- [x] Implement minimal CLI and entry point; keep raw error chain/traceback outside user outputs. Check EOF/cancel handling and no secret-bearing argparse values.
- [x] Add independent wheel smoke for installed entry point and an offline MCP dialogue using the installed bridge; no real endpoint.
- [x] Write Korean instructions with one command per block: update checkout, then standalone run, hidden local endpoint input, MCP catalog check, switch body from Avatar to AI Agent, spoken-code match. Separate registration/call/spoken acceptance and explain official AI pipeline/PC uptime requirement.
- [x] Run target tests, then full `pytest -q`, Ruff check/format, diff checks, build and independent wheel verification. Expect no regressions; record exact outcomes.
- [x] Commit implementation/docs. Obtain one fresh whole-branch review; fix Important/Critical findings with observed RED→GREEN and one green full-suite pass. Do not add unrelated polish.
- [ ] Normal push to existing feat/transport-soak, inspect hosted Windows/Linux matrix and numeric/JUnit artifacts. Give the user only the next one-command update step after those gates pass; live tool use remains pending operator evidence.

## Execution ruling

The user explicitly approved implementation, not another planning/permission round.
Implement natively in this session, with the requested final independent review, as an
assistant execution choice under the existing authorization. Use a linked ignored
worktree to preserve the clean managed feature checkout. Baseline/full tests run outside
the default sandbox because this environment's native SQLite sandbox stalls are documented.
