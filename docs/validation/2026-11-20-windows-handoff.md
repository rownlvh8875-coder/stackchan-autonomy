# Windows K151 handoff: offline preparation

Base `696460cc7671f94b71164904810ec93c68c7eb1f`, same `feat/wakeword-josu` / PR #3.
Windows source checkout was clean at330946a and fast-forwarded; no reimplementation
on another branch. No AGENTS.md was found in the repository or applicable ancestors.
The separate soak checkout, its untracked `%SOAK_REPORT%`, .local/private profiles,
keys and original backups were preserved. Python here is3.12.16; failed CI used3.12.10.

## Changes and bounded Windows evidence

Opt-in numerical timings now separate storage serial admission, shared executor
wait, operation and result delivery, with nested SQLite connect/BEGIN/schema/body/
COMMIT/close and a callback loop-lag monitor. Fixed labels and at most16 interruption
records contain no paths, SQL, arguments or exceptions. Actual lease deadlines,
durability, expiry/generation checks, stop latches and test lengths are unchanged.
CI collects the evidence on its existing2880-cycle scenario without retries.
The timer-descheduled post-delivery deadline path also reports a fixed code.

| Local Windows scenario | Result |
|---|---|
| Initial isolated160cycles, restart80, warmup20 | PASS,3.375s, cloud0/task0 |
| Preliminary diagnostic500cycles, restart125, warmup40 | PASS,10.656s, cloud0/task0; before precision refinement |
| Final diagnostic600cycles, default restart250/warmup100 | PASS,14.906s,2restarts/2renewals, cloud0/task0 |
| Final serial/executor/operation/delivery maxima | 0.0592ms /6.0133ms /20.4641ms /0.9332ms |
| Final SQLite BEGIN / COMMIT maxima | 0.7128ms /12.7258ms |
| Final independently sampled loop lag | 34.1409ms |

No historical failure reproduced on these finite baseline runs. Controlled short
tests separately delay a queue, saturate a one-thread executor, hold a real SQLite
writer, block loop delivery, and inject a slow lease check. Delayed control still
fails closed with cloud0, no replay and drained workers. Those injections validate
the measurement and safety mechanisms; they do not identify the historical cause.
SQLite wall time can include OS scheduling or physical I/O; it is not disk telemetry.

The diagnostics first failed6 tests, then passed. OTA/assets12 tests and owner-loop/
memory8 cases first failed for absent implementation, then passed. Added post-delivery
evidence first failed1 existing timer-descheduling assertion, then passed.
One independent read-only review found no Critical/Important and one Minor:
worker-complete/caller-canceled was labeled finished instead of delivery. A regression
failed on exactly that label before correction. Final diagnostic/cancellation subset
13PASS. A Windows coarse-clock timing assertion failed once (37ms versus40ms); probe
measurement moved to perf_counter, leaving all safety clocks/limits untouched.

## Offline standalone preparation

- Verified existing A/B16MB SHA and partition MD5 using the existing read-only tool.
  Sanitized OTA parser follows pinned IDF state/CRC/selection; drops20-byte seq_label.
  Snapshot seq1/seq2 are VALID with correct CRC; candidate isota_1 under both rollback
  policies. Running slot/current backup freshness/bootloader fallback/spare remain unknown.
- Re-downloaded only the3 public pinned ESP-SR model files into a new local folder.
  Checked all component file hashes, canonical pack offsets and the292607byte pack SHA
  `0255855e56bf72d1e072d2e0cbee4fb3ce1ac2c48f7fee6c8cd591f83e59ed95`.
  New local-only pack tool refuses overwrite and integrity/size mismatches.
- Added dormant NativeVoiceLoop reusing wake, question, guarded audio and API modules.
  Fake hit→question→3Mock API stages→speaker→cooldown→new wake is tested; cloud OFF,
  STOP, consent/readiness loss reject. Existing SWK1 and model ownership/wipe are retained.
- Extended memory policy to require the actual resident model and combined question/
  TLS/TTS capability watermarks. Actual readings, PSRAM allocator proof and device
  partition SHA provider do not exist yet; no readiness flag is asserted in app_main.
  [Installation/restore worksheet](../K151_NATIVE_INSTALL_PREP.ko.md) records exact
  known geometry, model candidate constraints and unexecuted restore commands.

## Final local verification

- Root495PASS2SKIP (libopus, Windows fork),102.90s with a private local Zig0.15.2/
  Clang20.1.2 wrapper and assertions enabled (`-UNDEBUG -D_DEBUG`). Earlier compiler-
  absent run491PASS5SKIP is retained as a separate observation.
- Standalone402PASS5SKIP,217.56s with NumPy2.3.5/cryptography46.0.4 and the same
  native Windows compiler. Skips: two symlink cases, opt-in SAPI synthesis, two
  Linux libcjson-dev decoder builds. Host tests are not target execution.
- Focused owner-loop/memory8PASS, timing/storage/deadline13PASS; all project Ruff
  checks and formatting334files PASS; project `git diff --check` PASS.
- No local IDF build: WSL's configured E: VHD path is missing; no working IDF/Docker
  was available. The pinned ESP32-S3 CI build is a separate result, never inferred
  from native Clang tests. The unchanged HOLD startup does not run a neural model.

## Actual GitHub CI and device boundary

Directly re-read original runs for exact base696460c:
[push44745307929](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44745307929)
4/4success;
[PR44745315318](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44745315318)
3/4success, Windows3.12 failure;
[S3 build44745315439](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44745315439)
success. **8/9, not green.** Failure job136318992024 passed487root and108PC tests,
then stopped on cycle2492/check_timeout,235.234s wall; maxcycle3.421s/gap4.329s.
No rerun requested. New-head results are recorded on PR #3 after push; this document
does not turn pending CI into success or claim that instrumentation fixes the cause.

Read-only PnP: present Bluetooth COM7 only; historical USB COM3 has Unknown status,
no present303A:1001 device. No port was opened/reset, no new flash backup read from
the robot, and no voice was recorded. Only esptool5.6.0 local --help was used.
No device flash/partition/NVS/eFuse/motor changes, model inference, paid API, real
standalone conversation, main merge, force push or deployment occurred.

Before device work, reconnect/power the USB device so its actual port can be
identified. Installation still requires a concrete operational image+SHA, sector
effects, current slot/boot compatibility, physical STOP/audio/drain and memory
evidence. Do not ask for installation approval while those remain unknown.

## Primary format references

OTA rules were checked in pinned IDF
[bootloader_common_loader.c](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/bootloader_support/src/bootloader_common_loader.c),
[bootloader_utility.c](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/bootloader_support/src/bootloader_utility.c),
[esp_flash_partitions.h](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/bootloader_support/include/esp_flash_partitions.h)
and the CRC seed in
[otatool.py](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/app_update/otatool.py).
Pack format follows pinned
[ESP-SR pack_model.py](https://github.com/espressif/esp-sr/blob/2f8c4b0459db5bbb39abd77adae27962d6d94bcb/model/pack_model.py).
