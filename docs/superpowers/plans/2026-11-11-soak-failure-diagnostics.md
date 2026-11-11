# Soak Failure Diagnostics Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD and one fresh final review.

**Goal:** Make the next failed soak actionable while retaining every safety stop and failing exit.
**Architecture:** Capture bounded failure metadata at the existing run_soak stop boundary;
measure cycle timings using paired monotonic/wall observations. No engine/control behavior change.
**Tech Stack:** Existing Python>=3.11, asyncio, sqlite3, Pydantic, pytest; no added dependencies.
**Spec:** [Failure diagnostics design](../specs/2026-11-11-soak-failure-diagnostics-design.md).

## Global constraints and review focus

- Historical user failure is unclassified; absence of sleep is operator evidence, not a cause.
- No retry, relaxed TTL/timeout, new accepted failure result or fabricated24h PASS.
- Fixed result-code allowlist; event/state enums and numeric/boolean metadata only.
- Preserve temporary DB isolation, CLI failure exits and cancellation/report semantics.
- Managed clean feature checkout; explicit file staging and normal feature-branch push only.

## Task1: Reproduction and diagnostics

Files: tests/test_soak.py, src/stackchan_autonomy/soak.py.
Consumes: real engine/SQLite control lease, existing soak interface.
Produces: optional failure metadata plus numeric timing maxima in SoakReport.

- [x] Inject real device disconnection, lease-clock expiry and storage error; require classified
  reports and no continued dispatch. Test private unknown codes and normal success. Observe RED.
- [x] Add bounded failure model, sanitize result codes, capture flags before cleanup and timing
  maxima without changing engine/action/control behavior. Observe targeted GREEN.
- [x] Verify full pytest, Ruff, wheel console smoke and real paced short run.

## Task2: Evidence, review and publication

Files: docs/SOAK.md, docs/WORK_LOG.md, docs/validation/2026-11-11-windows-home-soak-failed.json,
docs/DEVICE_ARRIVAL_RUNBOOK.ko.md, this plan.
Consumes: Task1 verified report fields. Produces: honest failure record and retry procedure.

- [x] Record uploaded failed result and limits; document fields and preserve known passing history.
- [x] Fresh read-only final review; one evidence-based fix pass for material findings.
- [ ] Normal feature-branch push; verify remote content and hosted CI. No PR or merge.

Progress and verification evidence are maintained in the local task ledger and WORK_LOG.
