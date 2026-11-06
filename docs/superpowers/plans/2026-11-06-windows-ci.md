# GitHub Reflection and Windows CI Plan

> Execute inline using writing-plans/executing-plans, then a fresh read-only review.

**Goal:** Publish the completed voice commit and add/run portable GitHub Actions
validation for Windows and Linux, Python 3.11 and 3.12.
**Spec:** User approved the recommended GitHub reflection then Windows CI next step.
**Base:** e9c4db7 voice commit; remote main currently e9e5c56.

## Scope / constraints
- Existing checkout/feature branch; no worktree or environment publication.
- Normal fast-forward push only; preserve remote work, no force push or PR merge.
- Offline application validation, no device, audio output, API keys or paid requests.
- Pinned official action SHAs and uv version, frozen lock, read-only workflow token.
- Windows missing fork/libopus cases are reported SKIP, never treated as executed.
- Run workflow on push/pull_request/workflow_dispatch; upload JUnit metadata only.
- Wheel smoke uses an independent temp venv, hashed frozen runtime requirements,
  and execution outside checkout. Cache/state/media are not uploaded.

## Review focus
Windows shell/path/encoding, exact interpreter, exit-status preservation, native
capability differences, independent wheel imports, secret/artifact scope and action refs.

## Tasks
1. [x] Inspect remote and official action refs; confirm available GitHub read capability.
2. [x] Add scripts/ci_verify.py for portable frozen export/install/wheel/CLI smoke and
   meaningful subprocess checks; exercise it on Linux before claiming readiness.
3. [x] Add .github/workflows/ci.yml matrix Windows/Ubuntu × 3.11/3.12, uv frozen sync,
   lint/tests/build/wheel smoke, Linux libopus and JUnit artifacts with minimal permissions.
4. [x] Validate YAML/workflow structure, run local full suite/build/smoke, independent
   review and corrections. Update README/CI.md/TEST_REPORT/WORK_LOG.
5. [x] Commit, fast-forward main and push without overwrite. Observe actual Actions
   matrix outcomes, diagnose/fix failures and report verified vs externally blocked checks.
