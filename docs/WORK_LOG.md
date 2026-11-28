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

## User real24h failure investigation — 2026-11-11

- Received Windows home report:35204.11s/34095cycles, engine_failure, traced growth75247B,
  no task growth/remaining tasks,136 restart checks, cloud requests0. User confirms no
  sleep/lid closure/reboot and no preceding warning. Historical root cause remains unknown.
  Original numeric report is preserved under docs/validation/2026-11-11-windows-home-soak-failed.json.
- Identified a diagnostic defect: the runner discarded its failing ActionResult and engine
  flags. Deterministic real-engine/SQLite expiry reproduces the same silent generic report;
  this demonstrates a possible failure path and does not establish the user's cause.
- Added bounded first-failure cycle/event/result and pre-cleanup state/flags, plus whole-run
  cycle duration/gap and paired wall-minus-monotonic drift maxima. Unknown result strings
  are redacted to a fixed marker. Existing success set, TTLs, timeouts, no-retry behavior,
  temp DB isolation, cancellation and exit semantics remain unchanged.
- RED:6 missing-field failures/13 existing passes. GREEN:19 soak tests/5.49s; full suite
 272 PASS/45.63s. A privacy fixture initially injected an unknown action code which the
  existing MemoryRecord already rejects; moved that injection to the engine-result boundary
  while retaining its actual step/storage effects. No production policy was loosened.
- Real paced120s:PASS,120.029s/1040cycles/4 restart checks, traced growth75585B, task growth0,
  remaining tasks0, cloud requests0. Max cycle0.130459s/gap0.160374s/wall drift0.000212s.
  Controlled real SQLite lease expiry produces device_fault/lease_lost at cycle3, CLI exit1,
  matching JSON stdout/file and no remaining tasks. Numeric evidence includes the source blob
  in docs/validation/2026-11-11-soak-diagnostics.json. These are not Windows24h results.
- Ruff check/format and diff whitespace pass. sdist/wheel build and independent installed
  Mock/MCP/voice/native Opus/memory/soak console checks pass. No dependencies changed.
- Fresh read-only review: no Critical/Important/Minor findings; independently19 soak tests,
  Ruff and whitespace pass. Existing failed JSON still validates with optional diagnostics null.
- Existing feature-branch upload is authorized; no new PR/merge, device/live API, credentials
  or environment configuration publication. Hosted Windows/Linux validation follows upload.

## Keep storage off the heartbeat loop — 2026-11-13

- Received another Windows report:33853.172s/32870cycles, stopped/ERROR with action fault
  and lease_lost=true; max cycle11.796s versus default10s TTL, max gap1.656s/drift0.021237s.
  Growth116610B, tasks0,131 restart checks, cloud0. Preserved as numeric FAIL evidence.
  Maxima do not identify the exact failed IO call or prove the Windows OS/disk trigger.
- Real-engine/SQLite RED: a slow file-memory snapshot starved renewal and lost ownership.
  Added separate async admission channels for runtime file memory and control operations;
  only one submitted Future per channel, slot retained until actual completion, ContextVars
  copied and abandoned errors consumed. In-memory SQLite remains on its creating thread.
- Control acquire/check/renew deadlines include admission+IO and a post-return monotonic
  check, bounded by min(operation timeout,TTL/4). Stop/fault rechecked after awaits; late
  acquisitions retained inside workers for release. Idempotent loss latches closed reason
  codes. Pending file work on cycle timeout/cancel stops further cycles. Async history and
  restart reads keep the soak sampler off the heartbeat loop too.
- Cleanup latches stop immediately, drains atomic workers and late acquisitions, releases
  by owner/generation and closes memory before directory removal; caller cancellation is
  deferred until cleanup finishes. FULL durability,10s default TTL,15s cycle budget,
  no replay/reacquisition, physical/media blocks and dependency lock are unchanged.
- Builder review rulings adopted: async admission before submission (avoid pool starvation),
  deadlines on delayed successful IO, late-handle retention, repeated-cancel cleanup and
  in-memory affinity. Targeted initial RED9+4, additional overdue-timer RED1; GREEN55.
- First full run exposed two deliberate report-contract updates: optional control reason
  defaultsNone; ownership storage verification failure now faults/ERROR rather than IDLE.
  Updated assertions to require fail-closed behavior and distinguish verification_error.
- Initial12s probe inadvertently delayed both recent() delegation and explicit snapshot,
  totaling24s and correctly triggering the15s timeout. Corrected fixture to one12s delay;
  no production timeout/TTL was relaxed. Default10s TTL then maintained3 renewals.
- Final reviewer Important: drain can spin on a completed Future before its callback runs
  under Python3.12 eager gather behavior. Independently reproduced with a bounded subprocess
  (RED4s timeout), fixed idempotent completion plus completed-Future pruning. No second review.
- Final56 target PASS/12.63s; full287 PASS/47.88s. Ruff/format and whitespace pass. Final
  default-TTL12s delay probe:12.014s,3 renewals, executed, no loss/tasks/API calls.
  Final paced120.038s:1009cycles/4restarts,8701B growth, task growth0/remaining0, cloud0.
  Numeric proof records all changed source blobs in validation/2026-11-13-storage-heartbeat.json.
- Final sdist/wheel and independently installed Mock/MCP/voice/native Opus/memory/soak CLIs
  pass. This proves the reproduced mechanism fix, not a real Windows24h PASS. Slow control
  storage or whole-process stalls still fail closed; paid budget IO remains outside scope.
- Normal existing feature-branch upload and hosted verification follow. No new PR/merge,
  live device/API, credential changes or cloud environment publication.

### Hosted deadline refinement — 2026-11-13

- First hosted candidate7d0a156 / run43362521047 passed Linux. Windows3.11 had8 failures
  and3.12 had5: legacy150–200ms lease tests encountered37.5–50ms fractional IO budgets;
  there was also a default history-loop fault and fixed startup polling. No failure was
  marked PASS and no safety stop was disabled.
- Ruling: replace arbitrary TTL/4 latency with the actual DB-observed monotonic validity,
  sampled before commit. Cold schema/setup before acquisition is not elapsed owned lifetime.
  Capture result/deadline/sequence together in the serialized worker. Checks cannot extend
  authority; renewal results must arrive before known expiry, and late results cannot revive
  faults. Schedule from remaining life, including already elapsed acquisition/commit latency.
  Unowned setup has a bounded max(operation timeout,TTL) wait, followed by a live-result check.
- Added three observed RED regressions for cold setup returning fresh authority, still-valid
  slow verification and renewal scheduling after slow acquisition. Updated stale-result tests
  to delay delivery after actual verification (not unowned setup). Held IO still has no grace.
- Runtime lease fixtures scaled150–200ms to1.5s to remove disk-speed assumptions; healthy
  heartbeat test waits3.2s (longer than initial TTL), and fake DB clocks still cross expiry.
  Scheduler waits for completed records rather than100 polling iterations. Every history
  cycle now asserts a healthy result, so an early fault cannot masquerade as bounded soak.
  Recorder timeout20ms remains unchanged and is exercised after control acquisition.
- New evidence justified a fresh limited deadline review: no findings; independently40
  lease/runtime/coordination tests PASS outside the default sandbox. An initial sandbox run
  stalled in durable SQLite acquisition; rerunning in the actual execution environment passed.
- Full290 PASS/59.81s, Ruff/format/diff pass. Rebuilt wheel and all independent console checks
  pass. Final default10sTTL probe: one12s memory delay/12.019s,3 renewals/no loss/tasks.
  Final paced120.031s:1026cycles/4restarts,17026B growth, tasks0/cloud0. Regenerated numeric
  evidence includes control.py plus all changed runtime source blobs. Hosted retry follows.

## User Windows PC real24h acceptance — received 2026-11-15 (KST)

- Confirmed remote feat/transport-soak at f659b39062ac9b00b2d022336705e3a2fc823c79 and
  hosted run43367322867 completed successfully. This is the code the operator updated
  before the successful10-minute check and subsequent real-duration retry.
- Preserved uploaded storage-24h-8681-28727.json byte-for-byte as
  validation/2026-11-15-windows-home-soak-24h-passed.json. Validated against SoakReport:
  passed=true,86400.047 real seconds, virtual_elapsed_s=null,83157cycles/83057measured,
  332engine restarts/restoration checks,20697B traced growth, tasks0, cloud0, no violations
  or failure. Cycle/gap/drift maxima4.688s/2.0s/0.016269s. Earlier FAIL evidence is retained.
- Updated SOAK, test report, next steps and arrival guide to record PC Fake/Mock real24h
  completion. Receipt date is not an inferred run date; the JSON has no source SHA or
  start/end timestamps and cannot independently establish absence of sleep. It does not
  establish total RSS/native memory or real hardware/media/paid API acceptance.
- Verification: original-byte equality and report schema/count/duration assertions pass;
  five changed Markdown files pass33 local-link checks, code-fence and whitespace checks.
  The original JSON retains its Windows CRLF newline; patch whitespace verification uses
  core.whitespace=trailing-space,space-before-tab,cr-at-eol to recognize that line ending.
  This update changes evidence/documentation only; no new runtime test result is claimed.

## K151 factory bring-up and PC extension direction — 2026-11-16 (KST)

- User confirmed K151, photographed firmware V1.6.2 and mobile app v1.2.12. Factory
  service checks show Xiaozhi and M5Stack HTTP200. After an initial host-unreachable
  Ping, ARP was present and the target answered4/4 with67–253ms. Exact initial cause
  is unknown. User confirmed Local Network in the official Motion page.
- Rechecked official main SHA28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400 against GitHub.
  Source shows robot-to-phone LAN connection, separate external MCP tool endpoint,
  app-version display and empty-tool-list Offline rendering. Production Avatar client
  compatibility cannot be inferred from the public example URL/key configuration.
- Read manufacturer issue126 answer and linked external endpoint example. Official
  MCP extensions preserve firmware/app but retain the official voice/AI pipeline.
  User explicitly selected that PC-function extension before direct PC OpenAI control.
- Recorded redacted field evidence and a one-tool PC connection diagnostic design.
  No runtime implementation, dependencies, token use, device/paid API calls, firmware
  changes or account resets. Full hardware acceptance and live PC tool use remain pending.
- Fresh builder check found nothing important left. Inspected the reference extension's
  raw JSON-RPC WebSocket transport; its SDK2 code is a reference only, not copied into our
  pinned SDK1.30 project. Recorded the required Avatar-to-AI-Agent switch for spoken checks.

## Official MCP PC diagnostic implementation — 2026-11-16 (KST)

- User approved the reviewed design. Created an ignored linked worktree; clean baseline290 PASS/64.22s.
- Core RED18 then expanded29 missing-feature failures; real local WebSocket plus pinned MCP SDK now passes32 tests/0.83s.
- Added observed RED2 for valid pre-initialization protocol Ping and standard initialization metadata, then accepted them without allowing pre-init tool calls. Added observed RED1 for arbitrary error text crossing the fixed-code boundary.
- One read-only per-run code/count tool; serial request admission bounds actual SDK task creation, not merely transport queues. Outbound TLS endpoint validation, hidden-value logging isolation, frame limits, initialization timeout and cancellation cleanup are covered. No real endpoint/token/device/provider was used.
- Added the direct pinned websockets15.0.1 dependency. Core target Ruff and whitespace checks pass; standalone CLI and full/package/hosted validation are next.
- CLI RED11 then GREEN: hidden input/EOF/warning failures, non-TTY behavior, no app dotenv,
  invalid URL before dial, secret argv without argparse echo, fixed error exits and Ctrl+C130.
  Combined target43 PASS/1.31s; full333 PASS/67.38s. Ruff/format/whitespace checks pass.
- Built sdist/wheel and independently installed it with locked dependencies. Existing
  Mock/MCP/voice/native Opus/memory/soak checks and the new installed console plus actual
  local WebSocket/SDK initialize/list/call all pass. No real endpoint/token/device was used.
- Added one-command-at-a-time Korean operator flow, local-only secret entry, distinct
  registration/invocation/spoken-code acceptance and Avatar-to-AI-Agent guidance.
  Final independent review and hosted Windows/Linux validation follow before user handoff.
- Fresh whole-branch reviewer independently ran43 target tests and identified Important2:
  SDK typed-validation failures leak via root logging, and normal late cancellation
  disconnects the session. Reproduced both with the real SDK, including unknown methods
  and malformed initialization metadata. The dedicated process now protects root handlers
  as well as named loggers, validates initialization and tolerates valid late/unknown cancellation.
- Reviewer set redirects aside without a demonstrated failure. A new two-local-server
  reproduction showed automatic connection to a nonapproved redirect destination.
  Ruling: grade as Important under the endpoint allowlist and reject all automatic redirects;
  cost: a legitimate future redirect needs an updated operator endpoint instead of transparent following.
- One fix pass observed6 RED regressions, then combined target49 PASS/1.60s. Full suite,
  rebuilt package and installed-wheel checks of the fixed source follow; no second review.
- Review rulings: outer URL whitespace trimming remains intentional; unknown nonstandard
  notifications remain fixed protocol failures (future extension messages may need support).
  The bridge is a dedicated single-session process, so scoped suppression of unrelated root
  logs is accepted; concurrent embedding is unsupported. Live service/Windows console/spoken
  acceptance requires operator/CI evidence. Hardware/media/OpenAI direct control remains excluded.
- The pinned SDK accepts tool requests immediately after its initialize response, while
  our first transport added a stricter notification gate. A further observed RED regression
  now covers that supported sequence and one later valid notification. It passes without
  permitting tool calls before initialization or emitting the check code twice.
  Final target50 PASS/1.33s; final full/package verification is being recorded below.
- Final fixed source: target50 PASS/1.33s, full340 PASS/64.46s, Ruff/format88files and
  whitespace/docs checks pass. Rebuilt sdist/wheel; both runtime modules match wheel bytes.
  Independent installed Mock/MCP/voice/native Opus/memory/soak and new local WebSocket/SDK
  tool dialogue pass. These supersede pre-fix333/339-suite results. Hosted publication follows.
- Ruling: support the pinned SDK's valid post-initialize-response request lifecycle instead
  of requiring an extra client notification gate. Cost: initialization readiness accepts
  the same post-response sequence as the SDK; calls before initialization stay blocked.

### Hosted Windows scheduler fixture refinement

- Runtime85f4230 hosted run43884297524 passed both Linux jobs and Windows3.11. Windows3.12
  reported340 tests,1 failure,2 skips: the existing remaining-lifetime heartbeat test
  failed its not-faulted assertion. Its report does not identify a control-loss reason
  or the exact slow Windows operation; the new PC bridge tests did not fail.
- The fixture left about0.5s of a1.5s lease after real acquisition delivery, then required
  actual disk renewal to keep ownership. A controlled0.45s renewal delay reproduced
  failure with the correct renew_timeout safety stop. Do not turn that valid stop into PASS.
- Ruling: isolate this one scheduling-policy test with a controlled monotonic clock,
  lease and inline storage. It requires renewal strictly after delivery and before known
  expiry; a mutation using the old full-TTL/3 schedule was observed RED, while the correct
  policy passes. Existing real SQLite heartbeat/contender/expiry tests remain unchanged.
  Cost: this unit tests scheduling rather than incidental filesystem throughput.
- Revised full suite340 PASS/61.31s. Production runtime modules are byte-identical to
  the verified release wheel; no TTL/timeouts/durability/runtime change. Hosted retry follows.

## Official AI to PC tool live acceptance — 2026-11-17 (KST)

- User pulled the existing feature checkout to83a8cde and ran stackchan-pc-mcp on the
  home Windows laptop. Provided CONNECTED/INITIALIZED/TOOLS_LISTED CLI output and the
  per-run diagnostic code293386. No endpoint/token is copied into repository evidence.
- After switching to the official voice-agent flow, user explicitly confirmed the PC
  invocation marker/count increase and the robot speaking the same code. Recorded live
  PASS for this read-only official-AI-to-PC extension. Exact final call count and a separate
  app-catalog screenshot were not supplied; do not invent them.
- Updated the runbook, execution guide, next steps and test report with the field evidence.
  PC OpenAI direct robot control, physical adapter/STOP/media and real-device24h remain
  separate. No cloud-side authenticated/device call, runtime/dependency change or new test.
- Verified six Markdown-only files, local links/fences, absence of JWT/device identifiers
  in the new field record, unchanged runtime/dependency blobs and patch whitespace.

## Official MCP historical soak summary — design, 2026-11-17 (KST)

- User asked to proceed with the recommended voice query for the completed 24-hour
  test. Inspected the live-verified bridge, source report, existing protocol tests
  and independent-wheel verification before proposing the extension.
- Prepared a small [design](superpowers/specs/2026-11-17-official-mcp-soak-summary-design.md):
  one additional zero-argument read-only tool serving the fixed historical PC Mock
  report, separate invocation evidence, strict provenance and installed-package support.
- Design approval is pending. No runtime, dependency, report or firmware change;
  no live endpoint/device call. Implementation and live voice acceptance remain pending.

## Official MCP historical soak summary — implementation, 2026-11-17 (KST)

- User approved the proposed design. Preserved native inline execution and reused
  the clean linked worktree, fast-forwarded to the design commit. Baseline340 PASS/61.64s.
- Loader/resource tests observed14 RED then14 PASS. The fixed original CRLF bytes
  are bundled with the package; bounded reads and a pinned SHA-256 reject corrupt,
  missing, oversized or changed evidence. Exact integrity checking validates the
  known original fields without importing engine settings/providers or parsing arbitrary reports.
- Pinned the two report paths to `-text` so Windows checkout does not change provenance.
  The authoritative report was not edited. Packaged/source parity is checked in tests
  and wheel/sdist checks; no arbitrary file/path/URL arguments are accepted.
- Real WebSocket/SDK tests observed10 RED/46 PASS before adding the summary dispatch;
  final target70 PASS/1.41s, full360 PASS/62.00s. Existing connection code/count remain
  independent of summary calls. Missing/corrupt evidence returns a fixed unavailable
  error while connection checks keep working. No raw resource/path/token is exposed.
- The installed-wheel probe rejects the old one-tool wheel (observed catalog assertion
  RED), then passes the new wheel from outside the checkout. Existing Mock/MCP/voice/
  native Opus/memory/soak checks pass. Wheel runtime bytes match source; wheel and sdist
  both contain the exact original evidence. Ruff/format93 files and whitespace pass.
- Updated the Korean operator guide with restart/update steps, voice request, separate
  marker and historical PC Fake/Mock scope. New live voice acceptance is pending;
  the earlier PC connection live PASS remains valid. Final review/hosted checks follow.
- Fresh whole-change reviewer found no Critical/Important/Minor issues. Independently
  verified source/wheel/sdist bytes and `core.autocrlf=true` resource behavior. No fix
  pass needed. Hosted matrix and operator voice acceptance remain separate checks.
- Pushed verified source925443e to the existing feature branch. Hosted run43961041890
  passed all four Windows/Linux Python3.11/3.12 jobs, including build and independent
  installed connection/summary tools. Downloaded all four JUnit/soak artifacts.
- Linux:360 PASS each (60.507s/63.449s); Windows:358 PASS +2 expected platform skips
  each (115.681s/161.816s). Target70 PASS in every job. Accelerated2880-cycle virtual
  24h scenario PASS in each, no remaining tasks/cloud requests/failure. These CI
  simulations are not a new real24h or physical-device run. Final update is docs only.

## Historical soak summary live voice acceptance — 2026-11-17 (KST)

- User's preceding pull fast-forwarded the Windows checkout to6ba5023, then the
  same PC bridge command connected/initialized/responded to tools/list. The supplied
  console includes exactly `PC_SOAK_REPORT_CALLED=1` for the summary invocation.
- User explicitly confirmed the robot described PC Fake/Mock PASS, about24 hours,
  83,157 cycles and332 restarts/restoration checks. These match the bundled original.
  No separate audio, exact raw utterance or app catalog screenshot was provided.
- Recorded live PASS for this historical-report voice query and updated the guide,
  runbook, next steps, validation JSON and test report. Earlier connection-code PASS
  remains separate. Do not infer new24h, hardware control, STOP or media acceptance.
- Documentation/evidence only; no runtime, dependency, original report, environment
  publishing or device call. Local Markdown/JSON/provenance checks precede the upload.

## GPT API robot replies — 2026-11-17 (KST)

- User explicitly prioritized GPT API answers spoken by the robot and asked to
  proceed promptly instead of more prerequisite connection tests. Confirmed key
  readiness only, never requested or received the key. Preserved factory firmware/app.
- Chosen route extends the live-proven official MCP path: official voice recognition/
  orchestration/playback, PC OpenAI Responses answers. Separate API persona/context,
  not this Codex session; no claim that MCP forces every utterance through GPT or
  that an independent voice backend/physical autonomy is finished.
- Native implementation in existing clean worktree, baseline360 PASS/62.32s. GPT
  service tests observed28 missing-feature RED then29 PASS/1.16s; a test fixture's
  assumed DB path was corrected to the actual env-priority path, without runtime changes.
- API requests use strict answer JSON, store=false, retry0, timeout and max600 output
  tokens. Only text plus last3 successful turns in RAM; no raw conversation in DB/logs.
  Shared persistent request budget survives restart/failure; storage is off the loop.
  Fixed official API URL/redirect rejection, input/output bounds and SDK debug privacy checked.
- MCP/CLI observed12 RED/57 PASS before adding conditional third tool and --gpt.
  Default two-tool command remains offline. GPT requires explicit cloud/key/model,
  reads local dotenv only in GPT mode and closes client/storage on exit. CALLED and
  ANSWERED markers distinguish invocation from validated API success.
- Current official model docs were checked read-only. Builder's guide example is
  gpt-6-luna/none for low-cost short replies. The model remains operator configured;
  optional reasoning setting observed2 RED then passed in the full suite. No account
  access/availability or price guarantee is inferred from public docs.
- Final full404 PASS/63.27s, target114 included, Ruff/format99files PASS. Built wheel
  runtime module bytes match source and original report bytes. Independent installed
  default/GPT SDK probes use a synthetic key and local HTTP transport only. Final
  installed result, fresh review and hosted matrix are recorded before handoff.
- Operator guide covers private local .env setup, same MCP hidden endpoint, explicit
  GPT request and optional existing-agent Character description. New paid API/voice
  acceptance remains pending. No firmware reset, motor/media call or environment publication.
- Fresh whole-change review identified Important1: top-level completed alone accepted
  incomplete messages/error envelopes/unknown or unsolicited tool blocks. Null nested
  items exposed raw SDK AttributeError; parent reproduced those plus an additional
  valid-reasoning rejection. Observed11 RED before the single fix pass.
- Validate envelope, exactly one completed assistant message, text-only content and
  usage shape; allow legitimate reasoning items. Target125 PASS/3.41s; revised full
  **415 PASS/61.74s** supersedes pre-review404. No deferred minors or second review.
  Independent installed-package verification of the fixed release follows.
- Fixed release rebuilt and independently installed: all existing CLI checks and
  real local WebSocket/MCP + OpenAI SDK answer probe PASS. Runtime module bytes match
  the wheel. No actual key/account/device was used. Hosted verification follows.
- Hosted run44085236332 tested fixed sourcea15cb95: all4 Windows/Linux Python3.11/3.12
  jobs SUCCESS, including independent wheel default/GPT probes. Downloaded and checked
  all4 JUnit/soak artifacts. Linux415 PASS each (59.803s/56.326s); Windows413 PASS+2
  existing platform skips each (96.171s/115.493s); target125 PASS in all4. Accelerated
  2880-cycle virtual24h scenarios PASS, no remaining tasks/cloud requests/failure.
- Final metadata update is documentation only; runtime stays byte-identical to the
  successful hosted source. Key is to be configured on the laptop; actual paid API
  model/account/voice acceptance is still pending. No new duration or hardware PASS.

## GPT API robot reply live acceptance — 2026-11-17 (KST)

- After reporting local .env saved, user followed the guided GPT run and reported
  normal robot speech. A single follow-up asked only whether the existing cmd had
  PC_GPT_ANSWERED with any number; user explicitly confirmed the marker was present.
  No extra paid question was requested for evidence collection.
- Recorded operator-confirmed live PASS for official voice → PC Responses answer →
  robot speech. Exact call number, runtime SHA/model, API response ID, raw speech,
  usage tokens and cost were not supplied; do not fabricate or generalize these.
- Updated the guide, runbook, README, next steps, test report and validation JSON.
  This remains a separate API conversation with official speech orchestration;
  independent voice backend, physical commands and duration claims stay separate.
- Evidence/documentation only. No key/endpoint read or cloud-side authenticated
  API/device request; no runtime, dependency, original report or environment change.

## Physical autonomy next milestone — source-backed observer design, 2026-11-17 (KST)

- User requested proceeding with the remaining autonomy stages and selected preparation
  of an official-firmware extension, explicitly not approval to install it.
- Rechecked official main via GitHub:28b9f0c matches the pinned source. Inspected
  external MCP direction, phone-hosted Avatar LAN, deployment RSA configuration,
  weak placeholder secret_logic functions, ReadPos fallback and NVS/servo startup behavior.
- Proposed a dedicated USB read-only observer first, with opt-in image understanding;
  no motor authority from unverified pose, no new LAN service/vendor credential reuse.
  Documented source-rebuild compatibility/recovery as a hard installation hold.
- Added a Korean staged roadmap and full design for a builder check. No product code,
  SDK installation/build, device/paid API access, credential read or firmware change.
- Fresh ESP32/Python builder review returned "nothing important left". Design approval
  remains the next gate; this preparation is not implementation or installation approval.
- 2026-11-17: Approved USB observer implementation
  - User approved the reviewed design; reused isolated worktree and native inline
    execution, wrote an implementation plan and observed missing-feature RED tests.
  - Added bounded SCOB protocol/client, identity profile and offline metadata-only CLI;
    same production C++ core/dispatcher host-tested with synthetic backend, plus opt-in
    official HAL/native USB adapter. No servo/UART reconfiguration or actuator calls.
  - Optional GPT observation shares persistent quota, validates consent/source before
    reservation, sends one JPEG/sanitized events and never joins text chat history.
    Existing default/text GPT MCP behavior preserved; cancellation drains serial IO.
  - Final offline459 PASS, target155 PASS, lint/format and isolated wheel probes PASS.
    Actual ESP-IDF6.1 ESP32-S3 build with enabled observer PASS; pinned input/output
    hashes recorded, binary stays local and is not approved for installation.
  - No physical device/API/credentials accessed. Installation remains HOLD for backup/
    restore, LCD/native USB identification, public auth placeholders, camera driver
    timing/recovery and explicit exact-image approval. Fresh review findings were fixed
    in one tested pass. CI44169302639 source391299e: all four jobs finally PASS; each
    Linux459, each Windows457+2SKIP, target155 all platforms. Windows3.12's initial
    existing1.5s heartbeat assertion and unchanged-code retry PASS are recorded with
    the uninstrumented cause, not mislabeled as a runtime fix.
- 2026-11-17: K151 backup/recovery preparation and compatibility disposition
  - User asked to proceed; reports USB connected but currently away, so no laptop
    command output or physical access is available. Prepared the next home COM query.
  - Rechecked live official manual, linked schematics and unchanged official source
    SHA28b9f0c. Confirmed source C/E LCD detection/init and GPIO19/20 native USB nets;
    actual unit LCD/COM/peripheral/driver behavior remains unverified.
  - Found official-repository contributor response issue134 (2026-11-12): production
    auth implementation is absent, no SDKCONFIG switch or published auth component;
    Xiaozhi AI.Agent has a separate connection. Official-app preservation stays BLOCKED
    for the prototype, not a condition solved by a full-flash backup.
  - Added Windows one-command-at-a-time stock readback/recovery guide: pinned esptool,
    manual download entry/re-enumeration, chip/security/16MB gates, ROM A/B reads in one
    bootloader session, local lengths/hash comparison, private second copy and stock
    reboot check. Distinguishes matching backups from successful restore and flash from
    eFuse/cloud/external controller state. No executable write/erase procedure is issued.
  - Documentation only; no runtime/lock changes, device calls, secret/NVS extraction,
    public issue/comment, installation or paid API. Hardware evidence remains pending.
- 2026-11-17: PC MCP transport recovery and Windows launch
  - User approved the proposed automatic reconnect/no automatic GPT replay/launcher
    work while physical backup evidence is unavailable. Preserved inline method and
    existing isolated worktree; wrote spec/plan and ran baseline459 PASS.
  - Added conservative fixed error classification and sequential fresh-session
    supervisor. Capped backoff, fatal-first groups and cancellable waits; no credential
    storage or physical observer reconnection. New flag defaults off, launcher opts in.
  - Fresh GPT client/context closes storage/HTTP before a next dial; persistent quota
    retained. Actual local SDK/MCP test cancelled an in-flight paid-call simulation,
    showed no replay, then accepted one genuinely new question with fresh context.
  - TDD RED17 then RED3 → target141 PASS+1SKIP, full480 PASS+1Windows-onlySKIP65.54s.
    Ruff/distributions and installed-wheel real local recovery/GPT/observer probes PASS.
  - Added UTF-8 CMD launcher with own-directory resolution, private endpoint prompt
    once and fixed Korean guidance. Hosted Windows launcher/whole-change review pending
    in docs/validation/2026-11-17-mcp-reconnect.md. No device, real endpoint, paid API,
    secret read, firmware install, OS startup task or environment publication.
  - Fresh review: fixed truncated HTTP/CONNECT handshake retry and SDK-swallowed output
    failures via independent task-group signal. Launcher now requires prepared venv
    with no package/network setup at launch; explicit uv sync is separate. Regraded
    empty observer argument to Important because it bypassed pre-input mode validation,
    then observed RED and fixed. Portable review RED4→97PASS+2WindowsSKIP. Cold-cache
    Windows cases await hosted execution; no fabricated local Windows RED claim.
    Cleanup-inclusive stability reset is a disclosed deferred minor.

  - Corrected full485PASS+2Windows-onlySKIP69.59s, lint/format, distribution and installed
    recovery/GPT/observer probes PASS. No runtime/firmware dependency changed.
  - Hosted first run44184962160: both Linux PASS; both Windows484PASS+2SKIP+1FAIL
    in the prepared launcher fixture. Diagnostic run44185692645 exposed missing
    pywintypes: PYTHONPATH did not execute installed pywin32 .pth setup. Fixed only
    test fixture site initialization after network denial; kept import precondition,
    assertions and cold-cache checks. No runtime/launcher change for this correction.
  - Final source8f0ad66, CI44186371845 attempt1: Linux/Windows × Python3.11/3.12
    all485PASS+2SKIP, zero failures/errors. Each recovery22PASS; Windows launcher2PASS.
    Downloaded all four JUnit/soak artifacts; each virtual24h2880cycles/86400s PASS,
    zero cloud requests/remaining tasks. Lint/build/independent installed probes PASS.
    Exact hashes and prior failures are in validation/2026-11-17-mcp-reconnect-ci.json.
    Actual Wi-Fi outage/robot speech recovery and GUI interrupt acceptance remain
    operator checks; one cleanup-inclusive delay-reset minor remains disclosed.
- 2026-11-18 (Asia/Seoul): User diagnostic MCP reconnection acceptance
  - User ran --reconnect without --gpt and supplied Windows console output after the
    instructed laptop Wi-Fi interruption/recovery. Initial session ended; waits2/4/8,
    two failed dials, then third-attempt CONNECTED/INITIALIZED and TOOLS_LISTED with
    a different check code. Diagnostic real-endpoint reconnection PASS by user log.
  - No new GPT response, robot speech recovery, measured outage duration or current
    Ctrl+C/launcher transition is established by this log. Next operator step: stop
    diagnostic bridge, run start-gpt.cmd, confirm GPT_READY/ANSWERED and robot sound.
  - Recorded sanitized live markers and updated current guide/report. Documentation
    only; no local device/official endpoint/paid API/secret access or firmware install.
- 2026-11-18 (Asia/Seoul): GPT-mode return and robot answer confirmed
  - User supplied start-gpt.cmd CONNECTED/INITIALIZED/GPT_READY/TOOLS_LISTED output;
    official app showed GPT tool registration. User then confirmed existing
    GPT_ANSWERED and robot voice with "응 나왔어"; no additional paid prompt requested.
  - Diagnostic automatic recovery and subsequent separately launched GPT answer/voice
    are PASS by user evidence. No field claim of an outage during paid processing,
    measured cost/latency, or real-device24h. Intervening tool-selection failure's exact
    cause is unknown; no speculative cache diagnosis or PC code fix is asserted.
  - Updated current guide, report and next steps; translated the earlier live record's
    remaining Japanese paragraphs into Korean. Documentation only, no runtime/lock,
    device/secret/paid API access or firmware/environment publication.
- 2026-11-18 (Asia/Seoul): First physical USB/ROM preflight
  - User supplied PnP COM3 plus Espressif303A:1001/MI00 IDs; COM7 is Bluetooth and
    excluded. Confirmed isolated esptool5.6.0 setup. Corrected a missing-backslash
    command presentation with fenced full-path Windows commands.
  - After manual Download Mode instructions, COM3 temporarily disappeared then
    reappeared with composite/JTAG interfaces. No-reset get-security-info failed with
    Write timeout; PC-side USB reconnect and one identical retry reproduced it.
    Screen off/green LED on did not establish ROM communication.
  - Pinned esptool USB-Serial/JTAG reset support checked without a local device.
    User --before usb-reset get-security-info succeeded: ESP32-S3 QFN56 rev0.2,
    USB-Serial/JTAG, flags0, Secure Boot/Flash Encryption Disabled. Subsequent no-reset
    flash-id succeeded:16MB/quad/3.3V. No protection setting changed; precise earlier
    timeout cause remains unknown. No MAC/keys copied into public evidence.
  - New private dated backup directory confirmed; first16MB ROM read instructed.
    A/B lengths/hash, stock reboot and restore remain pending until user evidence.
  - Reviewed pinned official LAN lifecycle/auth, BLE cached-buffer/battery callback
    and App Center OTA paths. No complete stock PC observation/control API established.
    Updated evidence/backup guide and removed unsafe COM7 example ambiguity. Firmware
    installation/auth HOLD remains. No cloud device/paid API call or firmware write.
- 2026-11-18 (Asia/Seoul): First original-flash read completed
  - User esptool output reports16,777,216bytes read from0 into factory-a.bin,
    1301.2seconds/103.2kbit/s and Staying in bootloader. Read used ROM/no-stub and
    no-reset before/after, explicit16MB, private newly created dated directory.
  - Instructed same-session B read into a distinct file. Actual filesystem lengths,
    B completion, SHA256 match, stock reboot and restore remain unconfirmed.
    Recorded completion metadata only; no original binary/MAC/credential upload.
- 2026-11-18 (Asia/Seoul): Original-flash A/B match confirmed
  - User B read completed16,777,216bytes in1309.6seconds/102.5kbit/s, staying in
    bootloader. PowerShell filesystem/hash output: A/B each16,777,216bytes with the
    same64-hex SHA256. Backup-file consistency PASS by user evidence; no binary upload.
  - Added sanitized machine-readable metadata. Separate private-media copy, stock
    reboot/app/GPT return and restoration writing remain unconfirmed at this point.
    Requested normal boot after PC GPT registration and existing functionality checks.
    No firmware write/erase, eFuse change or custom-auth compatibility claim.
- 2026-11-18 (Asia/Seoul): Stock return and camera baseline confirmed
  - User replied 잘된다 to normal boot/existing app/GPT_ANSWERED/robot voice checks
    after preparing PC GPT then short-pressing RST. Stock functionality return PASS
    by user report; no full post-boot log/current firmware version recollected.
  - User replied 보여 to official Monitoring Camera in Avatar mode. Basic official
    camera display PASS by user report. No image/video uploaded; no PC photo API,
    GPT vision, sensor reading, video latency/freshness or simultaneous voice claim.
  - Instructed closing Monitoring Camera and returning to AI Agent; final post-camera
    mode not separately confirmed. Separate private-media backup copy and actual
    restoration write remain unverified. Custom observer installation/auth HOLD remains.
- 2026-11-18 (Asia/Seoul): Stock observation route and support draft
  - User selected retaining the official app and checking manufacturer support first;
    did not authorize an independent firmware install or an external support post.
  - Inspected camera page/transport/remote authorization and deployment-time URL/key
    configuration. Avatar onClose requests warm reboot, so app preview does not prove
    a PC snapshot interface or uninterrupted AI.Agent coexistence. No secrets extracted.
  - Rechecked official main28b9f0c and issue134's two comments; no newer auth/SDK reply.
    Bounded camera API/SDK issue searches did not establish a supported stock PC API.
  - Prepared exact public-issue title/body requesting stock read-only JPEG/touch/IMU
    and owner authentication/coexistence documentation. No MAC, token, keys, backup
    hash or images included; no message posted. No product code/lock/config changes.
- 2026-11-18 (Asia/Seoul): Manufacturer inquiry cancelled; direct development requested
  - User explicitly said not to contact the manufacturer and to build the missing
    support. No issue/comment/message sent. Marked draft withdrawn and removed only
    agent-created local issue-title/body staging files to prevent accidental posting.
  - Reuse candidate is the existing SCOB/USB observer and Python client, not a fresh
    mock transport. Clarifying whether official-app compatibility is mandatory in the
    development mode; did not interpret direct development as device-install approval.
  - Read existing pinned build source: public two-OTA partition table, HAL NVS
    auto-erase/servo initialization and the separate Xiaozhi entrypoint erase path.
    Actual backup partition layout remains uninspected. No product code/device changes.
- 2026-11-18 (Asia/Seoul): Official-app requirement removed; direct-development spike
  - User said official app is optional and desired functionality takes priority.
    Target is a standalone GPT API firmware direction; USB remains a diagnostic path.
    This does not authorize device installation or claim compatibility with vendor services.
  - Built an explicitly experimental, stdlib-only backup-layout inspector: full-image
    SHA binding, fixed table offset/MD5, bounds/overlap checks, nonstandard-label redaction,
    fixed errors and explicit unknown active/spare slot. No serial/network/write/env access.
  - Synthetic standard table, wrong SHA, MD5 tamper with matching image hash, overlap,
    truncation, label privacy and actual CLI/input-unchanged checks PASS. Ruff/format PASS.
    No real backup image or device accessed; no paid API request. Product integration
    and installation are outside this spike. Operator metadata output still pending.
  - Follow-up source review found official-app Wi-Fi fallback, board-constructor
    hardware/timer coupling, shared24kHz audio framing, microphone errors returned as
    a positive sample count, legacy audio NVS writes and20s OTA confirmation. Recorded
    these as standalone-mode porting requirements, not completed firmware behavior.
    Proposed staged direct GPT/audio/observation/autonomy work; actual layout, active
    slot, memory headroom and independent TLS/audio operation remain unverified.
- 2026-11-18 (Asia/Seoul): Actual backup layout reported; standalone voice design prepared
  - User ran the hash-pinned spike at e81ffe4: full-image SHA and partition MD5 PASS,
    seven partitions with two5,177,344B app slots at0x20000/0x510000. Saved metadata-only
    evidence; no factory binary received. Active/spare slot and safe install remain unknown.
  - Wrote a reviewable native GPT voice design: no laptop/official app/server runtime,
    separate USB provisioning, bounded STT/Responses/TTS, persistent job/API reservations,
    fail-closed NVS with explicit new-namespace writes, STOP and no actuator commands.
    Camera/autonomous behavior remain later milestones. First implementation/build and
    actual device installation are separate decisions; no implementation approval claimed.
  - Fresh ESP-IDF/audio builder check returned "nothing important left". Design
    approval remains pending; the check is not implementation/hardware evidence. No real API,
    private key, device serial port, flash write or environment publication performed.
- 2026-11-18 (Asia/Seoul): User requested name/gesture activation instead of touch
  - User prefers a particular name or finger gesture to trigger interaction. Marked
    the touch-first proposal as superseded pending the concrete trigger choice; did
    not interpret this feedback as approval of the previous voice design.
  - Existing source has a Hi StackChan WakeNet setting. Custom Multinet configuration
    mentions Chinese pinyin; arbitrary Korean-name support is unverified. Si12T head
    touch/swipe is not visual-hand or finger-snap recognition. Asked for the desired
    name/movement to distinguish local voice, camera and audio-event detection.
  - No product code, microphone/camera activation, paid API or device write performed.
  - User then selected the Korean wake phrase "조수야". Updated the design's current
    requirement to local wake detection followed by question capture/automatic end,
    rather than touch-first or an assumed visual gesture. Trigger detector still unbuilt.
  - Confirmed ESP-SR2.4.7 cache and public HEAD bb552f1a559396a17681299cb3e199a0f1a4520a:
    Korean wake-word TTS training remains listed as planned; MultiNet supports Chinese/
    English. No claim that a config string enables Korean. Asked whether initial local
    voice enrollment is acceptable; model choice/accuracy and revised review remain pending.
  - User accepted initial local voice enrollment. Revised full design proposes a bounded
    MFCC/template-DTW prototype, MCU feature extraction and private USB enrollment,
    wake/ready/question VAD lifecycle, self-playback suppression, <=4KiB template blob,
    fail-closed NVS capacity and held-out real detection/false-wake acceptance gates.
    This is a proposed detector, not a verified Korean recognizer or speaker authentication.
  - A fresh embedded-audio builder check of the revision returned "nothing important left".
    Design implementation approval remains pending. No product implementation, voice
    recording, template training, microphone/device/API access or firmware installation.

- 2026-11-20 (Asia/Seoul): Continued `feat/wakeword-josu` / PR #3 from e8ee330 per user's pasted implementation instructions. Preserved prior unfinished worktree and existing synthetic fixtures. Diagnosed absent observability behind notebook `UNVERIFIED_NO_MATCH` (22,080frames does not establish truncation). Added input/VAD/FIR quality diagnostics, actual C++ private feature/calibration/score pipes, and RAM-only personal enrollment with frozen calibration and fresh evaluation. Windows runners select current mic rather than hardcoded9, save only a new ignored passing profile. Existing core, GPT/MCP path and hardware HOLD remain unchanged. Full local results and boundaries: [validation](validation/2026-11-20-josu-human-mic-diagnostics.md); [operator guide](../firmware/standalone/docs/2026-11-20-josu-human-mic.md). No actual Windows microphone/COM3/paid API/firmware/NVS/OTA/motor operation performed.

- 2026-11-20 (Asia/Seoul): Field enrollment kept failing at capture boundary even at3seconds; the requested no-speaking control also showed energy/tail activity with keyword rejection. No raw/private voice features received. Reproduced separated weak-tail expansion and quiet-noise premature rejection using synthetic/public data. Added conservative relative-peak energy region, retained400ms/physical-edge/format/clip guards, evaluated noisy quiet trials with the real frozen C++ matcher, kept falsewake FAIL and malformed/duplicate protections, and added3-second defaults/recording-finished marker. [Validation](validation/2026-11-20-josu-background-activity.md). Actual field success/device/API remain unverified and unexecuted.

- 2026-11-20 (Asia/Seoul): User's next PC session passed all3enrollment+5positive/10negative calibration capture quality gates, then returned generic local_helper_rejected before evaluation. No private PCM/features were retained or received, so exact historical cause remains unknown. Added host-only fixed calibration failure codes plus extreme trial indices/numeric distances, strictly validated before Python CLI output. Kept original core calibrator, successful SWK1 bytes, rejection/pass criteria and storage protections. Synthetic overlap/range and actual process-boundary/CLI privacy tests first4FAIL, then GREEN. [Validation](validation/2026-11-20-josu-calibration-diagnostics.md). No actual microphone/device/API access.

- 2026-11-20 (Asia/Seoul): User's new18capture session passed quality gates but returned calibration_not_separable; no raw/acoustic scalar data published or retuned. User accepted recommended built-in-wake support verification priority. Verified factory source pins Hi StackChan/ESP-SR2.4.7/IDF6.1, then copied current HOLD+core into an ignored throwaway project and actually compiled/linked model APIs and packed selected model. Build0, app334688bytes/model292607bytes, pack contents/SHA and ELF symbols checked, static DIRAM65482bytes. Model never executed; device/API untouched; runtime product source unchanged. Source/pack/size evidence and next integration sequence: [native wake preflight](validation/2026-11-20-k151-builtin-wakenet-preflight.md).

- 2026-11-20 (Asia/Seoul): User requested next builtin-wake integration. Added stateful24k→16k FIR, bounded NativeWakeController, shared VoiceDialogEntry, preserved legacy SWK1 wrapper. Local native hits admit one RAM-only exact Session epoch; durable budgets/read-back, cloud/owner/time/ordered paid-step guards stay closed by default. Added dormant ESP-SR2.4.7 K151 adapter with exact Hi StackChan model/shape/lifecycle validation; full public ABI doubles and real S3 compile/link, no SDK startup. Core RED31 then admission RED8→41PASS including legacy; SDK RED25→25PASS. Full root487PASS2SKIP, standalone338PASS43SKIP, selected NumPy PC105PASS3SKIP; pinned actual targetapp325792/staticDIRAM59030bytes. Link proof caught virtual-pointer GC; retained qualified thunk verified detect symbol. No device/actual audio/API/flash/NVS/OTA/motor/environment publish. [Evidence and remaining preparation](validation/2026-11-20-native-wake-voice-bridge.md). Prior1412660 Windows3.12 soak failed check_timeout and unchanged rerun failed renew_timeout; no relaxation or hidden substitution.

- Same native bridge task: sole fresh review found4Important issues (epoch crossing, shared SDK ownership, terminal-context retention, optimized PCM wipe). Promoted partial-read provider mutation to Important by effect. Reproduced9FAIL, corrected callback clock fixtures against pre-fix source, then70focusedPASS. Added listening-epoch checks, immediate provider checks, atomic single SDK owner/refusal of external cache, immediate error release and volatile PCM wipes with actual -O2 destructor store proof. Final whole standalone381PASS7Windows-onlySKIP with optional NumPy/crypto, root487PASS2SKIP, Ruff326files and actual S3/symbol recheck PASS. Finalapp325792bytes/staticDIRAM59030. Upstream SDK whitespace preserved as deferred minor with exact project diff scope. Physical/runtime/network/install exclusions remain HOLD; no re-review.
# 2026-11-20 Windows K151 handoff

Same feat/wakeword-josu/PR#3, clean checkout fast-forwarded to696460c. Added bounded
queue/SQLite/loop diagnostic evidence without changing safety limits; historical
Windows check_timeout remains unexplained. Local160/500/final600 finite Mock runs
passed, cloud0; root495PASS2SKIP and standalone402PASS5SKIP on Windows. Reverified
existing A/B16MB SHA, sanitized historical OTA candidateota_1, regenerated pinned
292607byte model pack. Added dormant single-owner loop and after-model/TLS memory
admission. Single independent review's delivery-cancellation label corrected via
RED→GREEN. PnP has no present Espressif; no port/reset/write/API/voice recording.
Target build is separate CI evidence; app_main remains HOLD. Details and remaining
installation/restore constraints: [handoff](validation/2026-11-20-windows-handoff.md),
[preparation](K151_NATIVE_INSTALL_PREP.ko.md). New head CI is reported on PR#3.

## 2026-11-20 USB reconnection and target asset verification gate

User reconnected COM3/303A:1001. One no-reset query failed; explicit USB reset
queried S3rev0.2/16MB/securityOFF. Read current table4KiB+OTA8KiB only; both match
verified factory snapshot. Current seq1/2 VALID→ota_1 candidate, not running/spare
proof. Requested hard-reset back to flash boot; actual face/menu unobserved.
No flash/partition/NVS/eFuse write, stub upload, new voice capture or API call.
Added dormant actual whole-DATA-partition SHA + atomic owner/STOP preparation.
Pinned draft model partition readonly/main-flash/F00000/1MiB includingFF tail.
17RED→44SDKPASS,2RED→5packerPASS. Single independent review found legacy-entry
lifecycle bypass; it plus stricter revocation boundaries reproduced3RED→101focused
PASS. Final whole standalone423PASS5SKIP/root495PASS2SKIP, Ruff335files PASS.
Actual new target CI remains separate. Preserved a6488de7/9 CI with SQLite COMMIT
renewal and installed-wheel Mock wait failures; no job retry/timeout relaxation.
[Fresh device and asset evidence](validation/2026-11-20-k151-current-usb-and-assets.md).
