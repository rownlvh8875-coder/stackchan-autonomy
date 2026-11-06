# Persistent Memory Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with test-driven-development and one fresh whole-branch review.

**Goal:** Optional, bounded metadata memory and explicit preferences that survive restart.
**Architecture:** Extend Memory with per-operation SQLite transactions, version1 migration,
resource-scoped typed metadata and a standalone CLI; engine reads fresh policy before dispatch.
**Tech Stack:** Existing Python>=3.11, sqlite3, Pydantic, uv, pytest, Ruff; no new dependencies.
**Spec:** docs/superpowers/specs/2026-11-06-persistent-memory-design.md and DEVELOPMENT_BRIEF §10.

## Global Constraints
- Preserve default memory_path=None, opt-in persistence and privacy/safety defaults.
- No raw speech, rationale, media, secrets, arbitrary preference keys or command replay.
- Existing coordination DB/leases/API limits are unaffected by memory clear/migration.
- Existing checkout/feature branch; no environment publish, force push or PR merge.
- Inline implementation chosen to continue the user's authorized next step without new gates.

## Review Focus
- Future/corrupt schema must fail without destructive recovery; migrate legacy atomically.
- Clock rollback and history eviction must not defeat retention or speech cooldown.
- Concurrent instances must see updated preferences/times without copying stale state.
- Storage failure after an already executed action must stop without replay.
- Windows paths and installed entry points must work outside the source checkout.

## Task 1: Versioned resource-scoped memory store
Files: memory.py, memory_store.py, models.py, tests/test_memory.py, existing metadata test.
Interfaces: Memory(limit=100,path=None,*,resource='stackchan:default',retention_s=604800,
clock=time.time); recent(), snapshot(), record(at,event,intent,result,*,status=None),
update_preferences(**typed changes), clear(), close(). Snapshot exposes recent metadata,
preferences, last_spoken_at/last_greeting_at and timestamped last observed robot status.
- [x] Write failing SQLite legacy migration, scope/expiry, evicted speech timestamp,
  fresh-instance visibility, typed privacy, clock rollback, future-schema and DB failure tests.
- [x] Run tests/test_memory.py; confirm new-contract failures.
- [x] Implement versioned atomic migration, per-operation connections and typed snapshots;
  preference interval 0..86400, automatic_speech_enabled bool, 7-day default retention.
- [x] Run targeted tests plus existing memory regression; commit after GREEN.

## Task 2: Engine policies and memory CLI
Files: engine.py, settings.py, memory_cli.py, pyproject.toml, test_memory_engine.py,
test_memory_cli.py, scripts/ci_verify.py.
Consumes Task1 snapshot/preferences APIs; Settings adds memory_retention_s.
Produces stackchan-memory show/set/clear, disabled without memory_path;
engine honors fresh preferences/times and stops on MemoryUnavailable.
- [x] Write failing restart greeting/cooldown, fresh preference/voice exemption,
  historical pose nonrestoration and pre/post-dispatch storage failure tests.
- [x] Write subprocess CLI set/show/clear/disabled/error tests and independent wheel smoke.
- [x] Implement engine/CLI with no model-driven memory writes, no stored commands.
- [x] Run all tests; verify Ruff, distributions and independent installed wheel; commit GREEN.

## Task 3: Review, records and integration
Files: MEMORY.md, README.md, NEXT_STEPS.md, TEST_REPORT.md, WORK_LOG.md, this plan.
- [ ] Fresh read-only final review; fix material findings with failing regression then GREEN suite.
- [ ] Document retention/schema/privacy/restore limits and actual test results.
- [ ] Commit verified work; publish a reviewable branch and inspect its Windows/Linux CI.
  Existing user GitHub workflow is continued without force or main overwrite.

## Execution ledger
Baseline aacc0b3; feat/persistent-memory. Steps and rulings are recorded in WORK_LOG.md.
Task1→Task2 snapshot/preferences/resource interfaces align; Task3 validates both.
