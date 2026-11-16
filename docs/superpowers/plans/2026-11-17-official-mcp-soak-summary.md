# Official MCP soak summary implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let the official robot AI query the completed home PC 24-hour soak report.

**Architecture:** Package a byte-identical copy of the fixed historical report and
verify its bounded bytes against the original SHA-256 before selecting numeric
fields. Add a second zero-argument MCP tool to the existing standalone bridge.
Preserve the connection diagnostic and its counter.

**Tech Stack:** Existing Python >=3.11, MCP1.30, websockets15.0.1, Hatchling, pytest.
No new dependencies. Execute inline, preserving the prior execution method.

**Spec:** [approved design](../specs/2026-11-17-official-mcp-soak-summary-design.md).

## Global Constraints

- Preserve K151 factory firmware, official app and `stackchan-pc-mcp` command.
- Name: `stackchan_pc_soak_report_summary`; no arguments; read-only annotations.
- Separate invocation marker: `PC_SOAK_REPORT_CALLED=N`.
- Historical PC Fake/Mock wall-clock test; receipt date 2026-11-15 KST.
- Preserve original report bytes; never read operator-selected paths or raw strings.
- Fixed unavailable error; no fallback PASS, raw exceptions, paths, token or report text.
- No new endpoint, dependency, automatic reconnect, paid API, device/media/DB action.

## Review Focus

- A wheel installed outside the checkout must find the report and return its true scope.
- Windows line-ending conversion must not invalidate or silently change the artifact.
- Corrupt/missing/oversized resources must return unavailable without leaking contents.
- Summary calls must not increment the connection counter or change its diagnostic code.
- Caller-supplied path/other arguments must never influence which data is read.

---

### Task 1: Fixed packaged report and safe summary loader

**Files:** Create `src/stackchan_autonomy/soak_summary.py`,
`src/stackchan_autonomy/data/windows-home-soak-24h-passed.json`, `.gitattributes`,
`tests/test_soak_summary.py`.

**Interfaces:** Produces `load_soak_summary() -> dict[str, object]` and
`SoakSummaryUnavailable` with fixed text `PC_SOAK_REPORT_UNAVAILABLE`.
Reads only the fixed `importlib.resources` package resource with a 16KiB bound.
SHA-256 `8ddbad0964b2249ed4d2b474b90836585f547b6e53d980c6d99f60eccc1cb728`
identifies the validated original bytes/fields. Pin both report paths to `-text`.

- [x] Write `test_summary_is_historical_pc_mock_wall_clock_evidence`: assert receipt
  date/basis, scope, historical/time mode, hardware=false, memory scope, PASS,
  86400.047 actual/86400 requested seconds, 83157 cycles, 332 restarts/restorations,
  20697 traced bytes, zero tasks/cloud and no failure/violations; no extra file text.
- [x] Write `test_resource_matches_original_evidence_bytes` and parameterized
  `test_unavailable_resource_never_becomes_pass_or_discloses_contents` using real
  temporary resources: missing file, malformed/extra/changed JSON, invalid numeric
  types, non-finite values, wrong duration/scope and >16KiB. Assert fixed error only.
- [x] Run `uv run --frozen pytest -q tests/test_soak_summary.py`; observe missing
  feature failures, then implement the loader and package the unmodified bytes.
- [x] Run the same command to PASS; commit `feat: package verified historical soak summary`.

### Task 2: MCP tool, installed wheel proof and operator guide

**Files:** Modify `src/stackchan_autonomy/official_mcp.py`,
`tests/test_official_mcp.py`, `scripts/ci_verify.py`,
`docs/OFFICIAL_MCP_PC.ko.md`, `docs/NEXT_STEPS.md`, `docs/TEST_REPORT.md`,
`docs/WORK_LOG.md`; add a validation record for offline/package/hosted results.

**Interfaces:** Consumes Task 1 loader/error. Adds the summary tool with empty
object schema and `additionalProperties=false`; uses the existing SDK error path
with the fixed unavailable code. A separate per-process summary call counter
records invocations, including unavailable calls; invalid arguments do not count.

- [x] Add real WebSocket/SDK tests for the two-tool catalog, interleaved calls,
  literal expected summary fields and separate counts; update earlier catalog sizes.
- [x] Add tests passing path/URL/extra arguments: error without invocation marker;
  then normal call returns the historical report. Supply a real missing/corrupt
  resource and prove fixed unavailable, safe console/log output and a still-working
  connection diagnostic. Run target tests and observe new-feature RED.
- [x] Implement catalog/dispatch/counter and fixed error handling; run target tests
  to PASS. Existing transport/lifecycle/secret protections stay unchanged.
- [x] Extend `scripts/ci_verify.py` to call the installed summary through the real
  local WebSocket/SDK dialogue from outside the source tree and verify original
  report hash/bytes and literal scope/numbers. Retain the connection-code probe.
- [x] Update Korean guide: stop old bridge with Ctrl+C, pull once, run same command,
  enter endpoint privately, ask “24시간 시험 결과 알려줘”, check new marker/numbers
  and PC Fake/Mock scope. Mark new live voice acceptance pending until user confirms.
- [x] Run `uv run --frozen pytest -q`, `uv run --frozen ruff check .`,
  `uv run --frozen ruff format --check .`, Markdown links/whitespace checks;
  expect zero failures. Build with `uv build --out-dir .local/soak-summary-dist`,
  run `uv run --frozen python scripts/ci_verify.py --wheel-dir .local/soak-summary-dist --require-opus`;
  expect installed checks PASS, no real endpoint/device/API used.
- [ ] Commit; fresh whole-change review, one tested fix pass if necessary, then
  normal push to existing `feat/transport-soak` (already authorized), verify all four
  existing Windows/Linux Python3.11/3.12 CI jobs. Record evidence and hand off one
  Windows command at a time. Do not create a PR, merge main or publish environment.

## Plan self-review

Both tasks cover the approved fixed report, bounded validation, numeric provenance,
independent packaging, protocol/privacy boundaries and operator acceptance. Task 2
consumes Task 1's exact loader/error interface. All five review focus conditions
have explicit tests or installed-artifact checks above. No new user decision needed.
