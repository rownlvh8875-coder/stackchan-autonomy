# Work log

Spec: docs/DEVELOPMENT_BRIEF.md. Plan: docs/superpowers/plans/2026-11-06-mock-mvp.md.

- Initial checkout is empty (unborn `work`); existing files not overwritten.
- User supplied an executable spec and explicitly requested implementation through
  Phase 3; proceed directly, without a separate design approval round.
- No worktree, firmware commands, physical motion, remote push, or paid API calls.
- Upstream clones are reference caches under /workspace/.cache/stackchan-upstream.
- Official web docs currently blocked by proxy policy. Added only docs.m5stack.com,
  developers.openai.com, openai.com to the saved network draft; not applied/published.
- Pre-flight: shared Decision/Observation/RobotCommand contracts will precede their
  consumers; absolute robot pose must be read at dispatch, never inferred from AI.
- Ruling: Phase 4–5 require interface/design only in this first run, per section 13;
  a read-only MCP discovery seam is permitted, physical execution remains disabled.

## Completed tasks and evidence

1. Phase 0 source audit: four default HEADs pinned; actual tool schemas, firmware
   boundaries, official MCP implementation and audio/retention differences recorded
   in UPSTREAM_AUDIT.md. Official web docs/pricing remain blocked by current policy.
2. Phase 1: pyproject/uv.lock, settings/models/ports, FakeRobot, Perception, CLI,
   robot/personality YAML and .env.example. Foundation tests: 12 passed.
3. Phase 2: Responses SDK adapter, strict JSON schema, local MockTransport fixtures,
   usage/reservation budgets, safe-idle failures, metadata-only optional SQLite.
4. Phase 3: bounded priority queue, state machine, scheduler, speech cooldown,
   one action owner, safety validation, duplicate/rate limits, stop/fault latches.
   Intermediate whole-suite results: 46 passed, then 50 passed with CLI/MCP tests.
5. Phase 4–5: discovery-only MCP seam with in-memory SDK test; VoiceInput and
   PlaybackAdapter ports; ARCHITECTURE/HARDWARE_BRINGUP/NEXT_STEPS designs.
6. Final review: fresh read-only review agent, no code mutations by reviewer.
   Reviewer did not assess live cloud/device/auth/firmware/Windows, unfinished docs,
   Phase 5 implementation or audit completeness. Those remain explicitly unverified;
   source audit/docs were completed by the main implementer.

## Review resolution

- Fixed: active request cancellation/overall cycle timeout could leave background
  dispatch running. Two regression tests RED→GREEN; cancel owner and latch fault.
- Fixed: unexpected adapter exception killed owner and stranded futures.
  Regression RED→GREEN; resolve failed/current/subsequent requests safely.
- Fixed: person detection overwrote VOICE_REQUEST. Regression RED→GREEN;
  preserve higher-priority user event and text.
- Review grading: unchanged-scene retry suppression and permanent speech dedupe
  were graded Important for this product (recovery/explicit requests would fail).
  Both reproduced RED→GREEN. Expire scene gate at 300s and retry unsuccessful
  analysis next observation; speech dedupe expires, explicit voice is exempt.
- Added regression checks for explicit repeated voice, bounded scene reanalysis,
  provider wall timeout, and opt-in image request body.
- No deferred code-review minors remain. No second review was claimed; fixes were
  verified by targeted tests and the whole suite.

## Final validation / retained configuration

- Final exact saved startup commands: `uv sync --frozen`, `uv run --frozen ruff
  check .`, `uv run --frozen ruff format --check src tests`, `uv run --frozen
  pytest -q`, and mock CLI: all passed. Pytest **60 passed in 7.73s**, zero failures.
- Previous full JUnit run: 60 passed in 10.16s; .local/pytest.xml retained locally.
- sdist/wheel built offline. Reinstalled wheel into the existing dependency venv
  and ran CLI from /tmp: mock/fake, one simulated action, zero cloud calls.
  Restored editable install with the tested .local/install.sh; repeated frozen sync
  checked 45 installed packages without changes.
- Writable UV_CACHE_DIR=/workspace/.cache/uv avoids read-only home cache in sandbox.
  SDK platform probing requires approved environment execution for tests here;
  no real API calls, TLS bypass or checksum bypass was used.
- Saved environment draft fields: install_script and start_skill; earlier network
  draft additions: docs.m5stack.com, developers.openai.com, openai.com.
  Persistence confirmed by status=saved. Runtime policy still has no custom hosts;
  saving did not apply changes or publish. User review/save/publish is outstanding.
- Repository remains on unborn `work`, all project files are new and uncommitted.
  No remote creation/push/merge, firmware modification or physical actuation.
  The current snapshot/new-task restoration has not been published or verified.

## Published environment continuation — Phase 4 MCP simulation

Plan: docs/superpowers/plans/2026-11-06-mcp-simulation.md.

- User published the previous environment and explicitly prohibited replaying old
  changes or publishing again. New task environment restored the source/cache/venv;
  baseline passed **60/60 in 3.60s**. Old changes were not reapplied.
- Current runtime networking is unrestricted. Official M5Stack product page and
  OpenAI structured-output guide returned HTTP 200. Audit/bring-up notes now separate
  those documented facts from still-unverified firmware images, account rights and hardware.
- Implemented mcp_contract.py, hardened mcp_robot.py, added simulation.py and
  --mode mcp-sim CLI. Actual remote adapter remains physical=True and blocks all
  write/capture/listen entry points; only read-only status/pose/touch are supported.
- Ruling: local simulator factory creates its own memory server/session and accepts
  no remote endpoint. This proves MCP contracts, not real HTTP/auth/ESP32 behavior;
  enabling real hardware prematurely would invalidate the validation boundary.
- Added audited Tool schema JSON with pinned source SHA and bundled MIT notice.
  No firmware/servo code copied; dependencies and lockfile unchanged.
- Pre-flight: RobotAdapter contracts remain unchanged; factory-owned simulator uses
  the shared ActionExecutor/SafetyPolicy. Remote read-only adapter is still blocked
  by ActionExecutor's physical guard. No global control lease is claimed.
- New protocol tests first failed on missing implementation. CLI and live-schema
  regressions then failed as intended and passed after implementation. Intermediate
  full suite: 102 passed. The independent review examined code and ran 46 tests.

### Phase 4 review resolutions

- Fixed: inherited classmethod connect could create a physical=False remote adapter.
  Remote connect now always returns the physical base class; offline regression RED→GREEN.
- Fixed: external SDK ValidationError was mistaken for local ValueError rejection.
  RPC/discovery decode failures now become a fixed-message MCPFailure and latch fault.
- Fixed: servo_init_ok alone did not prove command dispatch. Validate all ACK fields
  and motion_started for axes with changed targets; ambiguous replies fault without replay.
- Fixed: unknown semantic schema constraints were ignored. Reject unknown root/field
  constraints and validate the supported low-speed branch; four regression cases RED→GREEN.
- Review marker finding was treated as material fail-closed parsing: ok/available must
  be booleans; non-null error envelopes reject even empty strings. Four regressions fixed.
- Removed misleading server-cancellation test name and explicitly tested late remote
  application after client timeout. This is a remote-execution limitation, not a promise
  to retract commands. Fault latch prevents any retry/new command after uncertainty.
- Added no-op absolute target suppression; direct adapter regression RED→GREEN.
- No deferred review minors remain. Fixes were verified with full pytest, not a second review.
- Reviewer set aside hardware/firmware/electrical/timing/emergency stop, live HTTP/auth,
  global ownership, media retention/STT/TTS, cloud/billing, final artifacts/docs. These are
  either explicitly unverified or checked separately below; none were silently marked ready.

### Phase 4 final evidence

- `uv sync --frozen`: pass with pinned dependencies.
- `uv run --frozen pytest -q --junitxml=.local/phase4-pytest.xml`:
  **117 passed in 8.14s**, failures/errors/skipped all 0.
- Ruff check and format check: pass, 23 Python files.
- --mode mcp-sim --cycles 3 --event touch: IDLE, 1 simulated action, 0 cloud requests.
  Existing --mode mock --cycles 3 --person: same expected result.
- Offline sdist/wheel build: pass; schema JSON and MIT notice confirmed in wheel.
- Reinstalled the new wheel into the validated dependency venv and ran mcp-sim from
  /tmp: IDLE, 1 simulated action, 0 cloud requests. Restored editable install offline.
- Real HTTP/auth/device connection, physical motion/firmware, actual CV/STT/TTS and
  cloud account calls were not executed. Windows remains unverified.
- No environment draft updates, publication, remote repository creation, push or merge.
  Original .local baseline retained for review because HEAD is still unborn/uncommitted.

## Durable coordination follow-up

Plan: docs/superpowers/plans/2026-11-06-durable-coordination.md.
User approved the proposed cross-process lease, persistent API budget and process-failure tests.

- Added state_store.py, control.py, budget.py; connected ActionExecutor heartbeat,
  engine immediate lease-loss shutdown, CLI startup ownership and Responses provider reservations.
- Added state_path/control_resource/lease_ttl_s/budget_namespace settings and COORDINATION.md.
  Dependencies/uv.lock unchanged. Existing user files and prior uncommitted work preserved.
- Ruling: coordination is cooperative on one local host, using the same absolute DB,
  resource and budget namespace/limits. No gateway fencing or remote cancellation is claimed;
  applying it to arbitrary other controllers would require a gateway protocol change.
- Reservations are committed before HTTP and never refunded after uncertainty. Known token/failure
  metadata is persisted; lost responses cannot supply exact token/billing information.
- Wall time uses scoped high-water marks. Rollback delays expiry; forward jumps can advance it.
  DB failure blocks new actions/calls rather than falling back to in-memory state.
- Added isolated per-test databases, six-process lease and budget races, abrupt exit/expiry/
  reservation retention, stale generation, corrupt/locked DB, SDK MockTransport and CLI error tests.
- T10 now allows one action consumer plus one lease heartbeat, checks exactly one heartbeat,
  and still requires no leftover tasks after close and bounded memory/history across 1100 cycles.
- Reproduced and fixed CLI ExceptionGroup wrapping of lease/storage errors in the memory MCP
  context: return startup error metadata until context cleanup, then emit code 2 outside it.
- Reproduced and fixed lease loss leaving idle engine alive until its next timer; callback now
  stops it immediately with ERROR, and shutdown preserves ERROR.
- Intermediate full suite: 145 then 147 passed. New runtime tests were seen failing before fixes.
- Fresh read-only review independently ran 53 targeted tests in 5.16s and found a real fork
  identity bug. Parent/child copies shared owner UUID; child could renew/release parent's lease.
  Added actual fork regression, observed failure, bound identity to PID, then passed regression.
- Reviewer set aside earlier MCP baseline, actual device/auth/cloud/billing, gateway fencing,
  nonparticipants/different configuration, cross-host/network FS, clock-jump availability,
  unknowable usage after lost responses, malicious DB edits, injected retry policy, Windows/
  Python 3.11/long-duration operation. Those remain outside verified guarantees and are documented.
- No deferred review minors. Fixes verified with regression/full tests; no second review claimed.
- Final pytest: **148 passed in 13.70s**, failures/errors/skipped 0;
  .local/coordination-pytest.xml retained. Ruff/format pass (29 Python files).
- Mock and mcp-sim CLI demos each ran 3 cycles with IDLE, 1 simulated action and 0 cloud calls.
  Offline sdist/wheel build passed; control/budget/state_store modules were present in wheel.
  Installed wheel into the dependency venv and ran mcp-sim from /tmp with an explicit state path:
  1 simulated action, 0 cloud calls. Restored editable install offline; final lint/format passed.
- Real hardware, firmware, camera/audio, paid API calls, publication, draft changes and Git push
  were not performed. Physical command guards remain enabled.

## GitHub reflection request

- User explicitly authorized committing and pushing the completed project to the configured origin.
- Origin identity: github.com/rownlvh8875-coder/stackchan-autonomy; read-only ls-remote
  returned no refs, so main is the intended initial branch. No remote work will be overwritten.
- Fresh pre-push validation: 148 tests passed in 12.95s; Ruff/format checks passed.
- Candidate set: 48 project files; no credential-pattern matches or private/local artifacts found.
  Real .env, SQLite state, virtualenvs, caches, build outputs and .local backups stay ignored.
- Prepare one initial feature commit and a normal non-force push to main.
  Push confirmation is reported in the chat; environment publication is not part of this request.
