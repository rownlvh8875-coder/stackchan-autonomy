# Durable Control and API Budget Implementation Plan

> Execute inline with writing-plans/test-driven-development; final fresh read-only review.

**Goal:** Cross-process cooperative robot ownership and restart-safe rolling API budgets,
fully verifiable without hardware, credentials, or live APIs.
**Spec:** User approved the proposed control lease, SQLite API budget, and process failure tests.
**Architecture:** A shared local SQLite database uses short BEGIN IMMEDIATE transactions.
Leases have opaque owner IDs, expiry, and increasing generations. ActionExecutor owns a
heartbeat and checks ownership immediately before dispatch. Cloud requests reserve their
budget before HTTP; timestamps and aggregate usage survive restart. Fail closed on DB errors.
**Tech:** Existing Python/sqlite3/asyncio; no new dependency or lockfile change.

## Constraints / decisions
- Preserve current code and unpublished changes; no publication, push or worktree.
- No physical device control, firmware changes or live/paid API calls.
- Default shared DB: .local/autonomy.sqlite3, relative to the working directory.
  Processes must explicitly share its absolute path and resource ID to coordinate.
- A wall-clock high-water mark prevents rollback from resetting limits; forward clock
  jumps and external nonparticipating clients remain limitations. This is local-host
  cooperative ownership, not a gateway-enforced fencing protocol or physical stop.
- Mock mode still needs no API key; test databases are isolated per test.

## Review focus
Expired/stale holders, release after takeover, DB contention/corruption, wall-clock
rollback, request reservations after crash, canceled in-flight commands, task cleanup.

## Tasks
1. [x] Snapshot relevant baseline; add failing transaction/lease tests, implement
   state_store.py and control.py with acquire/renew/check/release and generations.
2. [x] Add failing persistence/window/concurrent-budget tests, implement budget.py;
   wire provider reservations and metadata-only token/failure accounting.
3. [x] Add failing heartbeat/loss/command-gating tests; wire ActionExecutor lifecycle,
   engine fault behavior and CLI startup ownership. Preserve physical guard.
4. [x] Run real subprocess contention, abrupt-exit/takeover, restart and SDK MockTransport
   persistence tests. Add state/resource/TTL/namespace settings and user documentation.
5. [x] Run full tests/lint/build/CLI, independent read-only review, fix findings with
   regressions and update TEST_REPORT/WORK_LOG. Do not modify environment draft.

## Interfaces
- SQLiteState(path).transaction(): bounded local write transaction, schema initialization,
  observed_time(db, scope, now) -> nondecreasing finite wall time.
- ControlLease(path, resource, ttl_s, clock).acquire() -> LeaseHandle | None;
  renew/check/release(handle) -> bool. Stale generations never renew/release a new holder.
- SQLiteRequestBudget(settings).reserve(now) -> bool;
  record_usage(input_tokens=0, output_tokens=0, failed=False); snapshot() -> BudgetUsage.
- ActionExecutor.claim_control() -> bool; heartbeat loss faults/cancels local work.
  aclose awaits owned tasks before conditional lease release.
