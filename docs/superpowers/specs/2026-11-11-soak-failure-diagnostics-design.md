# Soak failure diagnostics

## Problem and evidence

The user ran the requested Windows real24h Mock test with no reported sleep or lid
closure. Their numeric report stopped after35204.11s/34095cycles with engine_failure,
75247bytes traced growth, no task growth/remaining tasks,136 restart checks and no API
requests. No warning preceded the JSON. The report discards the failing ActionResult,
so the historical cause cannot be established. A silent control-lease failure is one
possible path; neither it nor a scheduling/clock/storage cause is proven for that run.

## Chosen scope

Improve the existing diagnostic report, with deterministic regressions using the real
engine and real SQLite lease. Retain the first failed cycle/event/result, engine state,
stop/fault/control-loss flags and numeric cycle-gap/duration/wall-clock-drift maxima.
Unknown result strings must be replaced with a fixed marker. No raw exceptions, text,
media, paths, device identifiers or environment values enter the report.

Approaches considered: rerunning unchanged24h gives no new failure evidence; loosening
timeouts/lease expiry or auto-retrying can hide a real safety failure. Recording bounded
diagnostics preserves failure semantics and is the appropriate next investigation.
This is a diagnostic fix under the ongoing stability-test task, not a claim to fix the
unidentified Windows failure. No new dependencies, live APIs, device actions or environment
configuration changes. The original failed report stays failed and is recorded as evidence.

## Acceptance

- Disconnection and deterministic expired lease stop the real engine and produce distinct
  metadata. Storage-cycle errors and unknown result strings remain failures and private.
- Success reports have no failure detail; existing counters/exits/isolation stay compatible.
- Timing maxima distinguish a slow cycle, gap between cycles and wall/monotonic divergence;
  these are observations and do not prove sleep or identify a causal OS event.
- Targeted tests, full suite, lint, wheel CLI smoke and a paced run pass. One fresh read-only
  review precedes normal push to the existing feature branch. No new PR/merge is created.
