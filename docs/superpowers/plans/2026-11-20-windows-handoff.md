# Windows handoff execution

User authorized same-branch code, offline tests and PR #3 updates, explicitly
opting out of repeated planning/approval questions. Device writes, recordings
and paid API calls remain unauthorized.

1. Preserve both existing checkouts and local data; fast-forward clean
   feat/wakeword-josu to verified remote 696460c. Read existing contracts.
2. Run one short isolated Mock baseline. Add opt-in bounded numerical timing
   evidence for serial admission, shared executor queue, operation, SQLite
   stages, result delivery and event-loop scheduling. Keep all safety deadlines.
   First fail tests for distinguishing these delays and preserving cancellation.
   Do not claim the historical CI cause without measurements from that failure.
3. Extend existing offline backup verifier with sanitized OTA records using
   pinned IDF CRC/state/selection rules. Test corrupt CRC, erased records,
   invalid/aborted/pending states, both slots and stale-backup limitations.
4. Reuse pinned model assets and existing memory/voice modules for remaining
   preparation. Verify pack hashes and placement constraints, and connect a
   dormant single-owner wake/turn loop. Unknown runtime evidence must reject.
   app_main stays HOLD until a concrete installation is reviewable.
5. Run root regressions, relevant standalone host/target checks available here,
   a bounded instrumented Mock scenario, lint and diff checks. Document exact
   results and unavailable tools, commit and push this branch without force.
   Read actual new Actions results; never substitute reruns for failed evidence.

Review focus: late worker completion after cancellation; delayed loop delivery;
no paths/SQL/arguments/errors in timing reports; no 'spare' inference from OTA;
no fabricated owner/assets/memory readiness; existing PCM wipe/epoch ownership.
