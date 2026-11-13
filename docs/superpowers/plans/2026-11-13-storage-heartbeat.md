# Storage Heartbeat Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline with TDD and one fresh final review.

**Goal:** Keep control renewal responsive during slow file-backed memory operations without weakening safety.
**Architecture:** Tracked, separately serialized executor Futures for memory and lease calls; cancellation
latched before dispatch; idempotent cleanup drains atomic IO before releasing/deleting resources.
**Tech Stack:** Python>=3.11 asyncio/concurrent futures/threading/contextvars, existing SQLite/Pydantic/pytest.
**Spec:** [Storage heartbeat design](../specs/2026-11-13-storage-heartbeat-design.md).

## Global constraints and review focus

- Keep default10s TTL, FULL durability, expired/generation checks, physical blocks and no replay.
- Delayed memory must not occupy the control queue; no thread affinity violation for :memory:.
- A timeout/cancel must not orphan an acquired handle or dispatch after stop.
- Await workers before shutdown/filesystem cleanup; cleanup cancellation cannot abandon live DB writes.
- Metadata only; the exact Windows trigger remains unproven. No cloud/device/environment changes.

## Task1: Storage execution and engine integration

Files: new src/stackchan_autonomy/async_storage.py, engine.py, action.py, soak.py;
new tests/test_async_storage.py, test_memory_engine.py, test_lease_runtime.py.
Consumes: existing sync Memory/ControlLease contracts. Produces: tracked worker calls, async engine
snapshot/recent access, responsive heartbeat and safe cancel/close semantics.

- [x] Observe RED for real memory-stall heartbeat reproduction and cancellation/late-acquire tests.
- [x] Implement the smallest tracked-worker adapter and engine/executor integration; targeted GREEN.
- [x] Preserve helper ContextVars/serialization/exception semantics; test actual expiry and slow-control stop.
- [x] Full regressions/lint, packaged CLI and default-TTL12s storage stall plus paced diagnostics.

## Task2: Evidence and publication

Files: docs/SOAK.md, TEST_REPORT.md, WORK_LOG.md, validation numeric evidence; this plan/spec.
Consumes: Task1 test results. Produces: bounded explanation, preserved Windows failure, retry steps.

- [x] Builder check of the storage/cancellation design; settle implementation details and record rulings.
- [x] Record what is proven and what remains unknown; fresh final review and one fix pass.
- [ ] Normal push to existing feat/transport-soak and inspect all Windows/Linux CI results.

Progress/rulings are kept in the local task ledger and WORK_LOG; no new PR/merge or environment publication.
