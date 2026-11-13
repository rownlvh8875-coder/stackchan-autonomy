# Offline stability diagnostic

`stackchan-soak` drives the actual autonomy engine using FakeRobotAdapter and
MockDecisionProvider only. It uses private temporary coordination/memory SQLite
files and ignores application env/.env, keys, URLs and operator database paths.
It never connects a robot, opens a public port or calls a paid API.

```text
# Accelerated24-hour virtual scenario: 2880 cycles ×30 virtual seconds.
uv run --frozen stackchan-soak --cycles 2880 --virtual-step-s 30 --report .local/soak/virtual-24h.json
# Real10-minute paced run, with periodic engine close/recreation.
uv run --frozen stackchan-soak --duration-s 600 --interval-s 0.2 --report .local/soak/realtime-600s.json
# Optional real24-hour run on a PC that will stay awake; not executed in this task.
uv run --frozen stackchan-soak --duration-s 86400 --interval-s 1 --report .local/soak/realtime-24h.json
```

Choose either cycles or real duration. Default1000 cycles, warmup100, restart every250.
`--virtual-step-s` explicitly chooses an injected engine clock; leases still use their
real coordination clock. `wall_elapsed_s` is measured with time.monotonic;
`virtual_elapsed_s` is separate and null when no virtual clock is selected.
A virtual24-hour PASS is not a real24-hour PASS.

The runner mixes timer/person/touch/voice fixture events, performs actual command
dispatch through fake ports, closes/recreates engines, and compares retained snapshots.
Harness command/cycle delays are0 to stress the software; optional real pacing is
separate from production defaults. A restart check does not restore robot position.

After warmup, it checks Python tracemalloc growth (default limit2,000,000 bytes),
live-task growth (default0 above warmed baseline), pending tasks after engine close,
and bounds for recent memory/transition/fake command histories (default100).
These are Python allocation estimates, not total process RSS/native-library memory.
The CLI is a standalone diagnostic; asyncio.run handles final loop shutdown if
unexpected pending tasks were detected. It reports those as failures before shutdown.
Library callers should use a dedicated loop/process rather than compare unrelated tasks.

Report fields contain counts/timings/fixed result or state codes/booleans only. No DB, raw media, text, keys
or environment dump is exported. JSON file replacement is atomic; use a unique report
path per run. A completed failed check exits1, invalid settings/storage exits2, and
Ctrl+C exits130 without creating a new PASS report. A run ending during warmup fails
as insufficient_measurement. It does not claim leak-free or crash-atomic operation.
Engine closes before its temporary DB directory is removed, including cancellation.

CI runs the accelerated scenario on Windows/Linux × Python3.11/3.12, plus a short
independently installed wheel/console-entry test. JUnit and the numeric JSON are the
only artifacts, retained7days. CI does not run a real24-hour soak on each push.

## Failure details — added 2026-11-11

The first unexpected engine result still stops the test with `engine_failure` and
exit1. The report now includes `failure` (null on normal completion), captured
**before cleanup stops the engine**:

- `cycle` and `event`: one-based cycle and the fixture event supplied by the runner.
  The engine may derive a person event from its observation; this is not an event trace.
- `result_code`: recognized engine/action result, or fixed `unrecognized_result` for
  any unexpected string. No exception message or arbitrary result string is exported.
- `engine_state`, `engine_stopped`, `action_stopped`, `action_faulted`, `lease_lost`:
  state/flags at the failure boundary. Control loss is not proof of a particular OS cause.
- `control_loss_reason` (added2026-11-13): fixed optional code. `lease_invalid` means an
  ownership/expiry check rejected the handle; `acquire_timeout`/`check_timeout` mean the
  ownership IO deadline elapsed. `renew_timeout`, `renew_rejected`, `renew_error` distinguish
  heartbeat deadline/rejection/exception; `verification_cancelled`/`verification_error`
  distinguish canceled/failed ownership verification. No exception text is exported.

Three numeric observations cover the whole run, including warmup:

- `max_cycle_duration_s`: longest monotonic duration of `engine.step`.
- `max_cycle_gap_s`: longest interval from one step's end to the next step's start;
  includes pacing, sampling/GC and restart work. The first gap includes initialization.
- `max_wall_clock_drift_s`: largest absolute wall-time delta minus monotonic delta
  observed across a step or inter-step gap. It is not cumulative clock drift.

Timing observations are diagnostic only; they do not prove sleep, a scheduler stall,
clock adjustment or storage failure caused the stop. They do not relax TTLs/timeouts,
retry a failed action or turn an engine failure into PASS. Older reports lack these
fields; their failure cause cannot be reconstructed retrospectively. Only
`engine_failure` creates the nested detail; other violations can have `failure=null`.

## User Windows run received 2026-11-11 — FAIL

The [uploaded numeric report](validation/2026-11-11-windows-home-soak-failed.json) requested
86400 real seconds and stopped after **35204.11s (9h46m44s)** /34095 cycles with
`passed=false`, `violations=["engine_failure"]`. Warmed Python traced growth75247bytes,
task growth0, remaining tasks0;136 restart/snapshot checks and cloud requests0.
The operator reports no sleep, lid closure or reboot and no warning before the JSON.
The report does not contain a source commit or detailed failure result. Its historical
root cause is **unknown**, not attributed to sleep or to a proven software defect.
This is not a real24h PASS. The earlier Linux10-minute and virtual24h results below
remain distinct historical checks.

Before retrying, update the existing `feat/transport-soak` checkout with
`git pull --ff-only` (stop on local changes/conflicts; never force reset), run a short
smoke, then a paced10-minute check before starting another real24h run. Keep the
original failed JSON. Use a fresh report filename and retain any preceding fixed-code
warnings. Windows **cmd** supports `%RANDOM%` in a report filename; PowerShell uses
the timestamp variable example in the [arrival guide](DEVICE_ARRIVAL_RUNBOOK.ko.md).
Copy commands one at a time; don't concatenate `uv sync` with `uv run`.

## User Windows run received 2026-11-13 — control loss, FAIL

The [second numeric report](validation/2026-11-13-windows-home-soak-control-loss.json) stopped
at33853.172s (9h24m13s) /32870cycles. Its failure is stopped/ERROR, action_faulted=true,
lease_lost=true. Largest cycle11.796s, inter-cycle gap1.656s, observed wall drift0.021237s.
The10s default lease is shorter than that largest cycle. Traced growth116610B, task growth0,
remaining tasks0,131 restart checks and no cloud requests. This is not a24h PASS.

Control authorization was lost. The maxima cover the whole run and do not identify the
specific failed-cycle IO call. They do not prove which Windows/disk/OS operation was slow.
Separately, a controlled slow file-memory call reproduced event-loop starvation and loss
of a real SQLite lease. The runtime fix below addresses that demonstrated mechanism.

### Runtime file IO isolation — 2026-11-13

Runtime file-memory reads/writes and lease acquire/check/renew/release use separate tracked
executor channels. Each channel admits at most one submitted Future. Cancellation of a caller
does not release that admission slot until its atomic operation finishes; canceled waiters
submit nothing. Slow memory cannot fill the shared executor or queue renewal behind itself.
The :memory: connection stays on its creating thread; async engine snapshot/recent APIs
also keep the soak runner's history/restart reads off the loop.

ControlLease records monotonic validity alongside its DB clock observation, before commit.
The serial worker captures the result, validity and observation sequence together. Held
ownership IO must finish admission/commit/delivery within that known validity; a check
never extends it, and a renewal cannot revive it after expiry. Renewal scheduling uses
remaining life instead of sleeping a full TTL/3 after a slow result. Initial unowned
setup may wait up to max(operation_timeout_s,lease.ttl_s), then must return a still-live
observation. Post-return checks also reject overdue results when loop timers are delayed.
The10s default lease, FULL SQLite durability, expiry/generation checks and no replay
remain. A canceled/failed ownership check latches stop; a late successful result cannot
clear it or dispatch a command. Pending memory IO at cycle timeout/cancellation also stops
the engine instead of starting another cycle behind uncertain work.

Shutdown latches stop before waiting, drains atomic workers, releases late acquired handles
and closes memory before temporary directory removal. Repeated caller cancellation is
propagated after cleanup finishes. An OS-level IO hang can delay cleanup; it does not permit
more commands. Whole-process stalls, slow control storage and external gateway fencing are
separate limitations; unsafe ownership still stops. The paid provider's synchronous budget
path is outside this offline fix. No real device/cloud/24h success is implied.

Local final validation after hosted refinement:290 tests pass. With the default10s TTL and15s cycle timeout,
a single12s file-memory delay completed in12.019s with3 successful renewals and no control loss.
A real120.031s paced run completed1026cycles/4restart checks, growth17026B, no task growth,
remaining tasks0 and cloud requests0. [Numeric evidence](validation/2026-11-13-storage-heartbeat.json)
records matching source blobs. These are short controlled checks, not a user Windows24h PASS.

The first hosted candidate passed Linux but exposed too-short Windows control budgets
and startup assumptions. The fixed TTL/4 policy was replaced by the actual validity
contract above. New tests accept slow setup before acquisition and slow but still-valid
verification, while rejecting stale acquired/verified results and never reviving a fault.
Small runtime-test leases were scaled from150–200ms to1.5s; logical expiry still advances
past that lifetime, and the healthy heartbeat test runs longer than its initial lease.
Scheduler tests wait for completed records, and every history-test cycle must remain healthy.

### Retry from an existing Windows cmd checkout

Run one command at a time. This form works from the home folder too:

```cmd
git -C "%USERPROFILE%\stackchan-soak-24h" pull --ff-only
```

After a successful update, run the10-minute check first. The absolute uv path supports
the portable ZIP installation without depending on the new cmd window's PATH.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" --directory "%USERPROFILE%\stackchan-soak-24h" run --frozen stackchan-soak --duration-s 600 --interval-s 0.2 --report ".local/soak/storage-10m-%RANDOM%-%RANDOM%.json"
```

Only after that result passes, start a fresh24h run using the same form with
`--duration-s 86400 --interval-s 1` and a new report prefix. Never concatenate commands or
reuse an unset `%SOAK_REPORT%`; cmd can leave it as a literal filename in the current folder.
Keep any test already running until it finishes unless explicitly choosing to interrupt it.

## Recorded validation — 2026-11-06

- Accelerated scenario: PASS,2880 cycles,2780 measured,86400 virtual seconds,
  26.192s wall elapsed;11 successful restart/snapshot checks.
- Warmed Python traced growth81,336 bytes; peak1,001,313 bytes. Max2 added live tasks,
  task growth0, remaining tasks0. Memory/transitions<=100, fake command history<=64.
- Real paced run: PASS,600.026s wall elapsed,2803 cycles/2703 measured,11 successful
  restart/snapshot checks. Warmed Python traced growth83,706 bytes; peak1,012,965 bytes.
  Task growth0/remaining0, max2 added live tasks, histories<=100 (fake commands<=64).
- Both runs: cloud requests0, no device interaction. Numeric evidence with the matching
  runner source blob/commit is saved in [validation JSON](validation/2026-11-06-soak.json).
  Neither result claims24 hours of real elapsed operation.
- Unit regressions deliberately retain memory/create pending tasks and prove failure
  detection, rather than treating the presence of a report as success.
