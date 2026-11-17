# PC MCP reconnection validation — 2026-11-17

User approved reconnecting the PC transport, not automatically resending GPT questions,
and easier Windows startup/configuration guidance. This extends the existing stock
firmware/official-app path; it does not change the observer firmware installation HOLD.

## Implemented and locally verified

- `--reconnect` opt-in supervisor, separate fresh single-session bridge per attempt;
  temporary-only retry, capped2/4/8/16/32/60s waits,60s initialized reset and cancellation.
- Fatal error classification wins in exception groups; auth,4xx/rate limit,TLS,
  protocol/output/redirect/unknown failures stop. Public codes contain no URL or reason.
- Fresh GPT client/context per connection, storage/HTTP cleanup awaited before any next
  attempt, same persistent budget. No request/result replay queue.
- `scripts/start-gpt.cmd`: prepared local venv only, own repository cwd, UTF-8, one launch,
  hidden endpoint input once, visible fatal exit. No Task Scheduler or secret file.
- Config validation before endpoint input/networking; observer/reconnect combination
  rejected before physical access. Existing single-session CLI remains available.

Baseline459 PASS66.15s. Task1 RED17 failures for absent recovery metadata/supervisor,
then71 target PASS1.59s. Task2 RED3 for missing opt-in/orchestrator, then target
**141 PASS,1 Windows-only SKIP /3.33s**. Pre-review full suite **480 PASS,1 SKIP /65.54s**.
Ruff check/format, distribution build and independent installed-wheel probes PASS.
The installed probe uses real local WebSockets/MCP, closes the first connection and
checks fresh tool state after recovery. Existing default/GPT/observer package probes
also passed. These are offline synthetic checks, not actual robot/service acceptance.

The SDK integration interrupts an actual Responses SDK MockTransport request after
its persistent reservation, verifies cancellation and old client closure before the
next session, then submits a new question. Exactly two requests/reservations occur;
the old question is absent from the second request's context, and raw content/keys
are absent from lifecycle logs. No paid request was made.

## Builder decisions and limits

| Decision | Reason and cost |
|---|---|
| Recovery defaults off; launcher opts in | Existing command behavior preserved. Existing users enable the flag or launcher |
| Reject USB observer with recovery | No automatic device reopening/snapshot retry. Observer users still restart manually |
| Keep public BridgeError import while factoring classifier | Focused transport code; no caller/API migration |
| Empty/normal WS close1005 is temporary | Valid empty closes can recover; backoff limits repeated dials if a server uses it as rejection |
| Fresh GPT context after reconnect | Prevent stale per-connection work/history. Short RAM dialogue is cleared; persistent quota remains |

Cancellation cannot undo a request already received/charged by OpenAI. A new server
tool invocation remains a new request, even if it repeats words or a per-session ID;
distributed exactly-once billing is not claimed. Normal connection detection/cleanup
takes time. The program must remain running on an awake laptop. Settings changes
require a process restart. No actual credential, firmware, camera or motor was accessed.

## Fresh review and one fix pass

Three important findings were accepted and fixed: an interrupted upgrade/HTTP proxy
CONNECT response became a fatal InvalidMessage/InvalidProxyMessage; SDK tool handlers
swallowed output failures; and uv startup could download before config checks. Added
real loopback EOF→healthy MCP and real SDK emitter-failure reproductions before fixing.
Portable RED4 failures (including empty option below) →97 target PASS+2 Windows SKIP.
Malformed HTTP remains fatal and broken output terminates without another dial.

The launcher's prepared/missing-environment cases now use an empty uv cache with uv
offline, a Python network-denial hook and no-download checks. These platform-specific
tests were written before changing the launcher but cannot execute locally on Linux;
do not claim a local Windows RED/acceptance run. Hosted Windows results follow below.

Review regrading: the empty `--observer-port ""` case was graded Minor by the reviewer.
It was raised to Important because silently ignoring an explicitly supplied invalid
mode reaches the secret-input/network path instead of rejecting configuration. The
new test failed at the forbidden prompt; testing option presence fixes it before input.
No USB access occurred in the old empty case, and none is enabled by this correction.

**Deferred minor:** the60s reset measures after cleanup, so a59s session plus2s cleanup
can reset delay early. This only shortens the next retry wait; cleanup still finishes
first, there is no request replay, and the longer elapsed attempt prevents a rapid
dial loop. Disclosed in the operator guide; not expanded into this one fix pass.

Reviewer set-aside items and executor rulings:

| Considered item | Disposition and practical limit |
|---|---|
| Actual endpoint/Wi-Fi/robot recovery | Operator acceptance pending; local recovery tests do not prove service availability |
| Billing/model permission/server reissuance | No paid calls; reservation/no-client-replay tested, exactly-once billing not promised |
| Physical observer/firmware/credential migration | Excluded, existing installation HOLD; forbidden combination rejected before input |
| Windows GUI/interrupt/codepage | Hosted headless path/config/cold-cache coverage; actual double-click/Ctrl+C and robot sound remain operator checks |
| CI/artifacts/publication | Verify after tested fixes and record the exact source commit; authorized normal branch push only |

No second review is requested. Final corrected full suite **485 PASS,2 Windows-only
SKIP /69.59s**, lint/format, distributions and all independent installed-wheel probes
PASS. Hosted results are recorded below after completion. Actual internet outage and robot voice recovery remain operator
checks in [the guide](../MCP_RECONNECT.ko.md).

## Hosted Windows fixture diagnosis

First source run44184962160 passed both Linux jobs but failed the prepared-environment
launcher case on both Windows versions (484 PASS,2 SKIP,1 FAIL each). The missing-env
case passed. A diagnostic import precondition, without product changes, reproduced
`ModuleNotFoundError: pywintypes` in run44185692645. The fixture passed dependencies
only through PYTHONPATH, which does not process pywin32's required .pth bootstrap.
It was not actually a prepared environment. The test-only network-denial hook now
uses site.addsitedir for the already installed dependency directory. Network blocking,
empty cache/no-download checks and the import precondition remain; neither launcher
nor runtime behavior changed for this correction. Final hosted evidence follows.
