# File storage must not starve the lease heartbeat

## Evidence and boundary of certainty

Windows diagnostic run requested86400s and failed at33853.172s/32870cycles. Its last
result is stopped, engine ERROR, action faulted and lease_lost=true. The largest cycle
duration is11.796s, gap1.656s and wall/monotonic drift0.021237s. The default lease TTL
is10s. This establishes control loss; maxima alone do not identify the slow OS/storage
operation or prove that the maximum belongs to the failed cycle.

Engine memory operations and control operations currently perform durable SQLite work
synchronously in the asyncio loop. A controlled file-memory wait prevents the real
heartbeat from renewing and reproduces loss. The fix addresses this reproducible
starvation mechanism; the exact Windows disk/OS trigger remains unproven.

## Approach

Move runtime file-memory and lease calls to tracked, serial worker calls using the
loop's shared executor. Memory and control must have separate admission slots so slow
memory does not queue the heartbeat behind itself. Keep SQLite synchronous=FULL,
the10s default TTL, expiry/generation checks, no automatic reacquisition/replay,
physical execution blocks and Fake-only soak isolation.

Increasing TTLs or treating lease loss as success can hide a safety failure. A separate
heartbeat thread alone leaves the main loop unresponsive and still races storage cleanup.
Tracked async file operations cover the Mock path while preserving fail-closed behavior.

## Components and contracts

- `async_storage.py`: serialized sync calls on executor Futures (not extra Tasks),
  ContextVar propagation, shielded worker lifetime and drain-before-close. Caller
  cancellation returns promptly; workers finish their atomic operations exactly once.
  Cleanup waits for those workers before reporting completion or deleting temporary DBs.
  Acquire an asyncio slot before submission and release it only on actual Future completion;
  canceled slot waiters submit nothing. At most one submitted worker per adapter avoids
  exhausting the shared pool behind a stalled memory call.
- Engine: keep thread-bound in-memory SQLite inline. Offload file-backed recent/snapshot/
  record calls; expose async snapshot/recent methods for the soak runner. Constructor
  initialization remains sync before ownership is acquired. Shutdown drains pending memory.
- Executor: acquire/check/renew/release go through a separate storage worker. Serialize
  claims; a late acquire handle remains owned by the executor for cleanup. Recheck stop/fault
  after each new await before dispatch. Cancellation during ownership verification latches
  stop, with no subsequent commands. ControlLease records conservative monotonic validity
  at the DB clock observation before commit. Result/deadline/sequence are captured together
  inside the serial worker. Checks never extend authorization; timely renewals can extend it.
  Held IO includes admission/commit/delivery within the known validity. Unowned acquisition
  has a bounded max(operation timeout,TTL) setup wait, then must return a still-live observation.
  Renewal sleeps at most one third of remaining life. Post-return checks reject late results;
  a fault cannot be cleared by a late success. Loss is latched idempotently.
- Cleanup: synchronous stop latch first; idempotent shielded cleanup waits for in-flight
  atomic DB operations and releases a late acquired handle before filesystem removal.
  Persistent OS-level IO hangs can delay final cleanup; they never authorize more commands.
- Memory timeout or caller cancellation with pending file work latches the engine fault;
  no repeated cycles queue behind an uncertain previous storage operation.
- Soak: use the engine's async file reads for restart snapshots and per-cycle history
  sampling. Keep the original failing reports and diagnostic semantics. Add a closed,
  optional control-loss reason code so future expiry, IO deadline and verification errors
  remain distinguishable without exporting exception text.

The paid cloud provider's synchronous budget path is outside this offline fix. Actual
devices, media and accounts remain unverified/disabled as documented.

## Verification

Test real SQLite/engine behavior: slow file memory permits a live heartbeat; an actual
expired/replaced lease still blocks; delayed renewal times out; stop/cancel during acquire
or check cannot dispatch; late acquire is released; memory close waits for a canceled
worker; helper ordering/ContextVars/exceptions/cancellation are preserved. In-memory
connection affinity, repeated close and no task/history/heap regression are required.

Full tests, independent installed wheel, default10s-TTL/12s delayed memory probe, paced
run, one final read-only review and Windows/Linux CI precede normal feature-branch upload.
No claim of Windows real24h PASS is made without the user's completed run.

## Hosted evidence refinement

The first hosted candidate7d0a156 passed Linux but failed Windows tests with37.5–50ms
control budgets (TTL/4 of test-only150–200ms leases), plus a default-lifetime history check
and a fixed startup poll. Cold DB setup can precede the actual lease timestamp; a fixed
fraction misclassifies still-live authorization. The revised observation contract above
replaces that fraction, without adding grace or changing expiry/generation conditions.
Legacy tests now wait for real completion and use realistic runtime leases; logical expiry
still uses controlled DB clocks. This material change gets a fresh limited deadline review.
