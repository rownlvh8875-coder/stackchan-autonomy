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

Report fields contain counts/timings/result codes only. No DB, raw media, text, keys
or environment dump is exported. JSON file replacement is atomic; use a unique report
path per run. A completed failed check exits1, invalid settings/storage exits2, and
Ctrl+C exits130 without creating a new PASS report. A run ending during warmup fails
as insufficient_measurement. It does not claim leak-free or crash-atomic operation.
Engine closes before its temporary DB directory is removed, including cancellation.

CI runs the accelerated scenario on Windows/Linux × Python3.11/3.12, plus a short
independently installed wheel/console-entry test. JUnit and the numeric JSON are the
only artifacts, retained7days. CI does not run a real24-hour soak on each push.

## Recorded validation — 2026-11-06

- Accelerated scenario: PASS,2880 cycles,2780 measured,86400 virtual seconds,
  26.192s wall elapsed;11 successful restart/snapshot checks.
- Warmed Python traced growth81,336 bytes; peak1,001,313 bytes. Max2 added live tasks,
  task growth0, remaining tasks0. Memory/transitions<=100, fake command history<=64.
- Cloud requests0, no device interaction. Real600s run is independently in progress;
  its completed result will be recorded separately after the process exits.
- Unit regressions deliberately retain memory/create pending tasks and prove failure
  detection, rather than treating the presence of a report as success.
