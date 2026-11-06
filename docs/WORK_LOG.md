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

## Offline voice follow-up

Plan: docs/superpowers/plans/2026-11-06-offline-voice.md.
User approved the recommended offline voice adapter/audio-conversion next step.
Base e9e5c561fed7be1d90f673a8fe720ce77a091c9e; local feat/offline-voice branch.

- Added audio.py (bounded s16le PCM/WAV, antialias normalization, /pcm payload),
  opus_codec.py (optional OS libopus raw16k/mono/60ms packets), cloud_audio.py
  (consent/model/voice/quota-gated SDK STT/TTS), voice.py (ports, fixtures and lifecycle).
- Existing AI/safety/lease/action pipeline is reused through SpeakingRobotAdapter.
  VoiceConversation handles explicit touch/voice only, blocks duplicate capture, and watches
  common engine stop_event. CLI voice-sim forbids --forever/timer and adds optional --opus.
- Ruling: this step implements offline voice/audio and API boundaries, not memory/UI/CI work.
  Fake ASR returns a fixture; Fake TTS generates a tone. Treating those as speech quality
  evidence would be wrong; live account/hardware checks remain separate.
- Checked official OpenAI audio docs HTTP200 and installed SDK3.46.0 signatures.
  TTS rawPCM24kHz/s16le is converted to audited gateway16kHz/mono and optional60ms Opus.
  /pcm payload generation is implemented; actual transport/token/playback is still blocked.
- No new Python dependencies/lockfile updates. Native libopus1.5.2 is OS-provided and not bundled.
  PCM mode works without native codec; missing codec produces an explicit optional capability error.
- Test-first: missing-module/CLI failures were observed, then functional tests passed.
  Added rate-type and cancellation-after-playback regressions, observed RED→GREEN.
  Intermediate full suite: 180 then187 passed.
- Fresh review independently ran39 new tests (2.87s) including actual Opus. Five important issues
  plus WAV frame alignment were reproduced. Added7 failing regression cases, then fixed:
  post-record cancellation before STT; injected SDK retries forced0; all terminal faults signal
  stop_event; disconnect safety events forwarded; voice/codec failure exitsCLI2; RIFF data alignment.
- WAV minor was treated as a material media-validation contract and fixed. No deferred review
  minors remain. Corrections were verified by full suite, not a second review.
- Review excluded real device/firmware, gateway HTTP/auth/ACK/STOP, live account/Korean quality/
  retention/billing, Windows/macOS/big-endian, external fencing, always-on capture/UI/face tracking/
  long soak, exact original-length Opus restoration and forced CPU-thread termination.
  Those limitations are recorded in VOICE.md and VOICE_TEST_REPORT.md.
- Final suite:194 PASS /15.95s; failures/errors/skips0; .local/voice-pytest.xml retained.
  Ruff/format passed36 Python files. Voice CLI ran both PCM and --opus: one capture/playback,
  IDLE,0 cloud calls; optional Opus generated7 packets. No real sound was played.
- Restricted cloud shell could stall thread shutdown (as with earlier SDK probe). Its owned
  smoke-test processes were terminated and CLI was verified in approved execution with a
  separate local state path. No verification bypass, physical I/O or live API calls.
- Offline sdist/wheel build passed. Environment draft/publication and remote push not performed.
- Wheel included all4 new voice modules and ran voice-sim --opus from /tmp successfully
  (capture/playback1, Opus7, cloud0). Restored editable install offline; final Ruff/format passed.

## GitHub voice reflection and Windows CI

Plan: docs/superpowers/plans/2026-11-06-windows-ci.md.
User approved publishing the finished voice work and proceeding with Windows CI.
Local base e9c4db7; remote main verified still e9e5c56, with no remote work to overwrite.

- Added GitHub Actions Ubuntu/Windows × Python3.11/3.12, frozen uv0.13.4 installation,
  Ruff, pytest/JUnit, distributions and independent installed-wheel CLI validation.
- Official checkout/setup-python/setup-uv/upload-artifact refs verified from upstream tags;
  full commit SHAs used, including peeled setup-uv commit. Read-only workflow token.
- Wheel verification exports hashed runtime requirements from uv.lock, uses a separate
  temp venv/exact selected interpreter and installed entry point outside the source tree.
  Temp path includes spaces; development venv is untouched. Linux requires native Opus;
  Windows's unsupported fork/native cases remain visible SKIP rather than claimed PASS.
- Local full suite:194 PASS /16.05s; failures/errors/skips0. Ruff/format and workflow
  YAML/matrix/permissions/SHA checks passed. Cached offline sdist/wheel build passed.
- Installed wheel passed Mock/MCP/voice/Opus runs: each IDLE, one simulated action,
  zero cloud requests; voice capture/playback1 and native Opus7 packets.
- Restricted shell build network denial resolved by existing verified offline cache;
  threaded offline tests/smokes used approved command execution. TLS/hashes retained.
- Credential-pattern scan passed; local state/media/keys/cache/build artifacts ignored.
  Workflow uploads only JUnit XML with seven-day retention, no application secrets bound.
- Remote Actions listing is accessible. Administration-permissions endpoint returned403;
  changing that setting is unnecessary and was not attempted.
- Remote matrix results will be recorded after normal fast-forward publication.
  Cloud environment draft/publication, actual hardware/firmware and live APIs are excluded.
- Fresh read-only CI review found no Critical/Important/Minor changes required. It independently
  checked syntax/workflow/platform lock entries and packaging/CLI interactions, without
  duplicating the full suite. Exact JUnit file selection was checked against the action's
  glob behavior. Actual hosted runners, optional Windows native features, existing application
  behavior, remote writes/admin and upstream tag verification were explicitly set aside;
  hosted results remain pending and parent verified upstream refs. No deferred review issues.
- Published voice e9c4db7 and CI3817ab1 to main by normal fast-forward push; remote hash
  matched. Run42151710686 completed successfully in all4 jobs. Downloaded JUnit confirms
  Ubuntu3.11/3.12 each194 PASS/0 SKIP and Windows3.11/3.12 each192 PASS/2 SKIP, no failures/errors.
  Windows skips: no trusted native libopus and no os.fork. PCM voice, subprocess races,
  independent installed entry points and packaged MCP resources passed on Windows.
- Hosted Node20 deprecation annotations prompted official Node24 action updates:
  checkout7.0.1/setup-python7.1.0/setup-uv10.3.3/upload-artifact7.0.2. Verified release tag SHAs
  and action manifests/input compatibility. Application code/lock/helper are unchanged.
  This targeted follow-up is validated by the next hosted run; no second review is claimed.

## Optional persistent memory follow-up

Plan: docs/superpowers/plans/2026-11-06-persistent-memory.md; spec beside it under specs.
User asked to proceed to next work after CI. Roadmap Phase5.4 / original brief §10 governs.
Base aacc0b3; existing checkout, new feat/persistent-memory branch. Inline execution;
no new worktree/environment publication. Baseline194 PASS /15.83s.

- Task1:12 new tests failed against missing contracts/privacy/schema protections, then passed
  after version1 SQLite migration, resource scoping, atomic per-operation storage, retention,
  typed preferences/metadata and independently retained speech/greeting times were implemented.
- Ruling: use a separate memory_store.py for migration/connection ownership — keeps the
  public Memory API focused, with no extra dependencies or storage authority.
- Existing metadata test's epoch0..4 fixture now injects clock4; those records are otherwise
  correctly expired under the new7-day retention. Assertions are unchanged.
- SQLite remains optional (:memory: when disabled); persistent control/quota DB is unchanged.
  Unknown schema/corrupt typed legacy metadata fail without destructive reset. Raw result
  strings are now a closed allowlist; preferences accept only bool/bounded interval fields.
- Task2:13 engine/CLI/preference tests failed before implementation, then passed.
  Engine uses its injected clock/resource, refreshes policy after model latency, claims
  command ownership before the shared speech check, and stores completion/observation
  timestamps separately. Memory failure latches ERROR and blocks subsequent actions.
- Added Settings.memory_retention_s and stackchan-memory show/set/clear entry point.
  Typed preferences only increase configured cooldown; background speech can be disabled,
  while touch/explicit voice stay available. No model-driven memory/profile writes.
- Ruling: retention must cover configured/preferred speech intervals — rejecting an invalid
  combination avoids expiring the suppression timestamp too early; operators must adjust
  retention before using a longer interval. Defaults7days comfortably cover300seconds.
- Real regression tests caught live schema changes being ignored, post-action memory failure
  exitingCLI0, and migration losing a speech timestamp outside a newly reduced history bound.
  Each failed first, was corrected, then passed with the whole suite.
- Task2 suite222 PASS /21.47s, failures/errors/skips0. Ruff passed. Independent installed
  wheel exercised Mock/MCP/voice/Opus and the new memory CLI, persisted preference gating,
  process restart cooldown and clear. Native Opus generated7 packets; cloud requests0.
- Limit: side effects and SQLite cannot commit atomically; crash after dispatch before memory
  commit can lose completion metadata. Failure stops the live engine, with manual recovery.
  Memory is not exact-once delivery, physical safety feedback or cross-host fencing.
- Initial feature branch65ea091 published normally; all4 jobs in run42159742164 passed.
  Draft PR creation was rejected by automatic approval review: it treats PR creation as
  an additional remote write requiring explicit user approval. No PR exists and no
  workaround/retry was attempted. Completed branch/CI work continues without that write.
- Fresh reviewer independently ran28 focused tests /3.45s and found4 Important issues:
  newly completed speech expired after large rollback, in-memory retention bypassed cooldown,
  MCP boot memory error escaped via ExceptionGroup, malformed YAML leaked raw config.
- Added7 failing cases for those findings and v1→v2 migration, then fixed all4. Separate
  logical speech_guard_at protects suppression without relabeling expired raw history.
  Retention/cooldown validation applies in both modes; MCP handles startup error before
  context exit; shared YAML parser normalizes parse errors without raw content.
- New version2 migration is backward compatible with legacy/v1. An additional regression
  failed when retained v1 history validation ran after migration commit; initialization now
  migrates/validates/expires in one transaction, preserving the original file on failure.
- Final fix pass:230 PASS /23.63s, failures/errors/skips0. Ruff/format, distributions and
  independent installed wheel all passed; Mock/MCP/voice/Opus/memory runs cloud requests0.
  Corrections verified by tests, no second review claimed; no deferred minors.
- Review rulings: discarding expired/count-evicted invalid rows is permitted by the retained
  metadata contract; future/corrupt schema and concurrent writes remain transactional.
  Clock-jump conservative delays are accepted availability costs, not cooldown bypass.
  Historical pose is the last recorded observation, never restored; touch/voice exemptions
  and prior control claim remain intentional. Edits after a snapshot are visible next read,
  without an atomic settings-to-device guarantee. Explicit clear resets clocks/preferences.
  Crash/cancellation between command and metadata commit, conflicting participant settings,
  malicious DB/model edits, network FS/cross-host fencing and hardware/live-cloud behavior
  remain outside guarantees. Windows native DLL/fork cases are explicit SKIP; hosted matrix
  and distribution/native verification are done by the parent, not claimed as reviewer work.

## Device-free HTTP and sustained stability follow-up

User approved the recommended HTTP integration and sustained mock verification.
Base42cf1a3 on feat/transport-soak, with existing memory draftPR1 unchanged.
Plan/spec: docs/superpowers/{plans,specs}/2026-11-06-transport-soak*.md.
Baseline230 PASS /24.68s. No environment publication, device or paid API use.

- Task1: actual SDK StreamableHTTP/uvicorn fixture bound only127.0.0.1:0.
  Initial10 failures reproduced raw ExceptionGroups and context error wrapping;
  added6 RED cases for raw upstream JSON in SDK logs and invalid timeouts causing I/O.
- Adapter uses current streamable_http_client, fixed MCPFailure boundary, preserved caller
  cancellation/consumer exception identity and closed-adapter latch. No RPC replay.
  ContextVar-scoped SDK transport log filter prevents raw validation/body logs while
  unrelated client contexts keep their logging. Timeout validated before any network I/O.
- Server fixture owns dependency SSE watcher cleanup; it does not cancel arbitrary client
  tasks. No extra live tasks after a successful full connection/server lifecycle.
- Existing late-application test timed out before dispatch under load. Increased its
  timeout to1s and added explicit dispatch-entry evidence before testing late effects;
  it still proves local timeout is not remote rollback, without relying on50ms setup.
- Task1 targeted73 PASS /10.48s (17 HTTP +56 existing MCP), Ruff/format passed.
  Auth missing/wrong/revoked, expired session, truncated/stalled response, identity change,
  explicit reconnection, cancellation, body error and cross-origin redirect all exercised.
- Ruling: use actual loopback sockets rather than ASGI-only mocks — tests transport framing
  and lifecycle with a test bearer token. Proxy bypass is restricted to localhost in test
  fixture environment; external proxy/CA trust remain intact. No public port is exposed.
- Task2:12 initial soak tests failed before implementation;13 passed /3.13s after adding
  explicit cancellation/temporary DB cleanup regression. Cancellation had recreated the
  removed DB during lease release; AsyncExitStack now closes engine before directory deletion.
- New stackchan-soak uses init-only Settings sources, own temporary files, Fake/Mock,
  real duration or bounded cycles with optional virtual engine clock. Mixed events,
  periodic engine restarts/snapshot comparisons, warmed tracemalloc/task/history measurements
  and nonzero failure exits are exercised; deliberate heap/task leaks fail the diagnostic.
- Accelerated virtual24h run:2880 cycles,86400 virtual seconds,26.192s wall,11 restorations,
  traced growth81336 bytes/peak1001313, task growth0/remaining0, cloud requests0.
  Separate real600s run is active; its result is not yet claimed.
- Intermediate full260 PASS /36.70s; Ruff/format, sdist/wheel, independent installed
  Mock/MCP/voice/Opus/memory and new soak entry point passed, all cloud requests0.
- CI adds accelerated2880×30s scenario and exact JUnit+numeric soak JSON artifacts (7days).
  Tests bind only loopback; no user state/media/keys or DB artifacts are uploaded.
- Real paced600s run completed PASS:600.026s wall,2803 cycles,2703 measured,
  11 successful restarts, traced growth83706/peak1012965 bytes, task growth0/remaining0,
  histories<=100, fake history<=64, cloud requests0. Runner blob matches551cdf6.
  Both numeric reports committed under docs/validation; not a real24-hour claim.
- Fresh read-only review confirmed two Important teardown issues: SDK swallowed failed
  DELETE (HTTP500 returned normally) and inactivity timeout allowed indefinitely trickling
  DELETE body. Six failing regressions then fixes verify status failures, absolute deadline,
  body-error note/identity,405unsupported and cancellation during cleanup.
- Connector now owns bounded same-origin DELETE (SDK auto-termination disabled), records
  session_cleanup_confirmed and raises fixed failures. Original consumer errors retain
  identity with fixed notes; external cancellation retains precedence. Normal200/204 confirms
  protocol termination only, not physical stop. No second review; no deferred minors.
- Final local suite266 PASS /40.83s; HTTP/MCP target79 PASS /13.80s. Ruff/format,
  distributions and independently installed Mock/MCP/voice/Opus/memory/soak CLI passed.
- Ruling:405is a valid unsupported-termination response — preserve protocol compatibility
  with fixed warning and explicit False confirmation, leaving remote expiry unproven.
  Cost: operator must rely on gateway expiry/manual cleanup when DELETE is unsupported.
- Review rulings accepted: SDK GET reconnect is distinct from tool replay; error identity,
  cancellation, raw log filtering, redirect auth and timeout prevalidation are tested.
  Fixture watcher ownership and causal late-effect test are deliberate. Init-only settings,
  warmed growth plus pending-task check, history/restoration and distinct clocks meet scope.
  Dedicated-process tracer/task interference limits, unique interrupted-report paths,
  native/RSS/scheduler/hardware/real24h limits remain explicit. Exact artifact paths exclude
  secrets/DBs. Pending real-run documentation is now resolved by completed evidence above.
- First hosted run42166297818: Linux jobs passed; both Windows jobs correctly reported
  insufficient measurement in the0.4s duration unit test (only2 warmup cycles completed).
  The test had incorrectly assumed machine throughput, while the runner's failure was valid.
  Added controlled0.25s/provider latency, observed RED locally, then asserted independent
  monotonic elapsed bounds plus exact success/insufficient-measurement consistency.
  The full2880-cycle CI diagnostic still requires PASS. No production checks were disabled.
- After platform-test correction:267 PASS /40.68s, failures/errors/skips0 locally;
  Ruff/format pass. Diagnostic source is unchanged, so completed10-minute/virtual24h
  source-blob evidence remains valid. Hosted final matrix is being rechecked.

## Product arrival operating guide — 2026-11-06

- User requested a detailed Korean manual from parcel arrival through physical validation,
  based on product manuals, and GitHub upload. Added the D00–D10 runbook, Mermaid flowchart,
  blank local acceptance record and links from README/bring-up/next steps.
- Read the official M5Stack StackChan, download, M5Burner and Qoder guides and Astral uv
  installation page over HTTPS (all HTTP200). Captured firstboot servo movement, World app,
  original-controller compatibility, 2.4GHz requirement, automatic OTA, account-unpair loss,
  power/RST distinction, factory recovery and the2026-08-07 LCD revision requirement.
- Distinguished factory functionality, current read-only MCP API, missing physical adapter,
  actual media/AI development and subsequent supervised/1h/real24h acceptance. No physical
  stage is marked passed. The user's PC24h completion remains unconfirmed.
- Verified local Markdown links/anchors and fences; parsed the flowchart with Mermaid11.14.0;
  compiled the embedded Python example and checked its robot calls are discover/status/
  touch_state only. Compared documented app/soak CLI options with installed --help output.
- Ran documented Mock3-cycle, MCP3-cycle, voice1-cycle and30-cycle soak examples in a private
  temporary directory: all exit0, each cloud_requests0; app state IDLE and soak passed with
  no violations. These are Linux CLI checks, not a Windows PowerShell or real-device run.
- Fresh read-only review reported no actionable Critical/Important/Minor findings. Final
  clarity pass added the project directory/PATH before the new-window read-only example.
- Documentation only: source, lockfile, original development brief and environment config
  unchanged. No firmware/device/gateway connection, paid API, new PR or merge was performed.
  User authorized normal upload to the existing feat/transport-soak branch.
