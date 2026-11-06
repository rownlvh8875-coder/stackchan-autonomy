# HTTP and Soak Verification Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD, and one fresh whole-branch review.

**Goal:** Verify real loopback MCP HTTP failure behavior and sustained offline engine stability.
**Architecture:** Test-owned SDK/uvicorn loopback fixture; narrow adapter connection boundary;
isolated bounded soak CLI with explicit wall/virtual clocks and metadata-only reports.
**Tech Stack:** Existing Python>=3.11, asyncio, MCP1.30.0, uvicorn0.54.0,
Starlette1.10.0, sqlite3, tracemalloc, pytest; no new dependencies.
**Spec:** docs/superpowers/specs/2026-11-06-transport-soak-design.md.

## Constraints and review focus
- Existing memory PR remains separate; new feat/transport-soak starts at42cf1a3.
- No devices, live APIs, production credentials, external ports, main/PR merge or environment publish.
- Real server binds only127.0.0.1:0; proxy/CA settings remain for external traffic.
- Auth/session/stream failures must not leak secrets or replay uncertain requests.
- Caller cancellation/body errors and failed cleanup must remain observable and bounded.
- Soak ignores app env/.env and never uses an operator's DB; real vs virtual time is explicit.
- Heap/task/history thresholds, restarts and nonzero failure exits must measure actual behavior.

## Task1: Real HTTP fixture and connection behavior
Files: tests/http_gateway.py, tests/test_mcp_http.py, mcp_robot.py.
- [x] Build test-owned ASGI auth/fault controls with real SDK session manager and ephemeral socket.
- [x] Write failing connect/auth/timeout/stream/session/cancellation regressions; run RED.
- [x] Normalize transport connection failures, preserve body cancellation/error, latch adapter.
- [x] Verify fresh explicit reconnect, no RPC after fault, blocked physical/media calls,
  and clean server/client shutdown; targeted/full tests GREEN; commit.

## Task2: Offline bounded soak runner
Files: soak.py, pyproject.toml, tests/test_soak.py, scripts/ci_verify.py.
Interfaces: SoakConfig (cycles or duration, pacing, warmup, restart cadence, virtual step,
heap growth bound), async run_soak(config)->numeric SoakReport, stackchan-soak CLI.
- [x] Failing tests: warmed bounds/restarts, no task leaks, env/DB isolation,
  real vs virtual elapsed, invalid/too-short runs and process exit/report behavior.
- [x] Implement actual engine loop, temp SQLite, traced heap/task/history measurements,
  cadence restarts, monotonic duration/pacing and fixed errors; targeted GREEN.
- [ ] Run real600s paced soak and accelerated86400s virtual run; keep their distinct reports.
- [x] Add independent installed-wheel entry-point smoke; full tests/lint/build GREEN; commit.

## Task3: Evidence and review
Files: docs/TRANSPORT_TEST_REPORT.md, docs/SOAK.md, README/NEXT_STEPS/CI/WORK_LOG, this plan.
- [ ] Fresh read-only reviewer; material fixes use RED→GREEN plus whole suite, no second review.
- [ ] Record actual durations/counts/limits; never claim24h real run or device verification.
- [ ] Publish verified feature branch, observe Windows/Linux3.11/3.12 CI and inspect reports.
  No new PR creation without specific approval; existing draft PR1 is not changed/merged.

## Ledger
Track task evidence/rulings in WORK_LOG. Task1/2 share existing engine/settings/adapter contracts;
no incompatible new interfaces. Task3 consumes their real reports and verification output.
