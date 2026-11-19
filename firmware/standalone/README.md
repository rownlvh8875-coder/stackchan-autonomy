# K151 Standalone GPT: portable safety core (reconstruction)

**STATUS: PORTABLE HOST TESTS + ESP32-S3 COMPILE-ONLY DRIVER. NOT APPROVED FOR DEVICE INSTALLATION.**

This directory is a fresh reconstruction of **portable** mechanisms from the
approved 2026-11-18 standalone design, not a recovery of the prior Codex
workspace. The prior uncommitted `firmware/standalone` implementation was not
present in the latest GitHub branch. Never overwrite recovered work with this
branch without an explicit review/diff.

## Included

- `core/standalone_core.hpp`: bounded, versioned SCFG v1 framing, CRC integrity,
  contiguous nonce-bound feature chunks; one-way STOP/epoch invalidation;
  bounded per-request/overall deadlines; no self-wake during processing;
  cloud calls disabled at boot; rolling durable *reservation* ledger for
  2 conversations/min, 30/hour, 100/day. The ledger counts **three** potential
  billable requests per reservation even on failure.
- `tests/standalone_core_test.cpp`: independent host assertions for protocol,
  errors/replays, timeouts, STOP, stale callbacks, voice lifecycle, and budget.
- `tests/test_standalone_core_build.py`: offline g++ C++20 compilation/runner.

The C++ header contains no ESP-IDF dependencies and may be linked into an
ESP-IDF application *after* the real board adaptation is reviewed.

## Validation

```sh
python -m pytest -q firmware/standalone/tests/test_standalone_core_build.py
# or, without pytest:
g++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic \
  -Ifirmware/standalone/core firmware/standalone/tests/standalone_core_test.cpp \
  -o /tmp/standalone_core_test && /tmp/standalone_core_test
```

## Not implemented or proved in this reconstruction

- Actual Korean wake accuracy or acoustic thresholds, physical USB receiver,
  verified K151 board power/mute/reset, LCD and microphone/speaker operation,
  Wi-Fi/TLS/clock/HTTP + STT/Responses/TTS clients, speaker feedback suppression,
  ROM recovery/OTA slot handling.
- A real NVS implementation and ESP32-S3 CODEC-DRIVER COMPILE now exist, but
  neither has been approved for device execution. Host tests and ESP32 builds
  cannot establish real hardware timing, RAM/PSRAM, audio or paid API behavior.

No automatic flashing, no manufacturer AI startup, no servo initialization,
no factory settings erase, no model fallback, and no cloud request are provided.
USB enrollment transfers wake features only; the portable host receiver validates
SWK1 profiles before invoking a simulated durable write. A guarded NVS adapter
exists in the compile-only ESP-IDF app, but physical local arming and MCU USB
driver are **not** supplied.
The durable-store callback MUST perform one atomic NVS commit; if a commit
fails or its outcome is uncertain, the caller must not send any API request.
First installation must explicitly initialize an absent ledger; a missing or
corrupt ledger must not be treated as a reset to zero after provisioning.

See `docs/superpowers/specs/2026-11-18-standalone-gpt-design.md` for the source
of requirements and the outstanding physical-installation HOLD.

## Experimental on-device wake feature algorithm

`core/wake_features.hpp` adds a bounded 24kHz-to-16kHz anti-aliased
resampler, 25ms/10ms 26-mel/13-cepstral-feature extractor, 64x13 int8
output, DTW matcher, profile CRC/version validation and held-out
positive/negative rejection calibration. A profile with up to three
stored templates uses at most 2507 bytes. The host test uses **synthetic
sine waves**, so it proves only math/format behavior, **not recognition
of the Korean phrase `조수야`**. It is not voice biometric authentication.

A real ESP32 integration still needs microphone I2S, segmentation/VAD,
fixed-point or measured CPU optimization, wake/noise corpus, duration/RAM
measurements, tests after reboot and the real-device acceptance criteria:
18/20 new spoken positives at 1m, at most one false wake per quiet/ordinary
60-minute negative period and zero wakes in 20 robot-playback trials.
A failure must leave cloud wake activation disabled instead of using
paid always-on STT as an undocumented fallback.

## Offline USB feature-enrollment protocol (next stage)

`core/usb_enrollment.hpp` includes the capped SCFG stream reader and a strictly
**offline** receiver. It accepts `enroll_begin` (length + profile CRC), ordered
`enroll_features` chunks, and `enroll_commit` only after an explicitly armed
local enrollment mode. It validates the fixed `SWK1` 64x13 int8 wake template
format and calls a supplied persistence callback; a failed/uncertain commit
latches a fault until a fresh, verified startup. `status` and `stop` remain
available during enrollment. STOP aborts registration; resume is not a USB
command. Invalid/raw PCM profile bytes cannot reach the persistence callback.

Fixed 18-byte `SACK` replies carry only operation, result, state, nonce, sequence
and CRC32; **CRC is not authentication**. No keys, identifiers, raw voice,
features, or conversation contents are reflected. Configure and cloud-enable
remain unsupported and cloud stays off. The streaming codec has a 2-second
incomplete-frame timeout. An eventual device driver must read USB without
blocking physical STOP; this host component does not claim that guarantee.

`tools/scfg_offline.py` validates a *previously obtained* SWK1 feature blob and,
with explicit `--output`, writes only a private local enrollment packet bundle.
It never opens COM/USB, microphone, network, or GPIO. It never records or
calibrates a real voice. The robot-side voice capture, feature extraction,
first-time enrollment, and operator-approved install are still missing.

```bash
python firmware/standalone/tools/scfg_offline.py PRIVATE_FILE.swk1
python firmware/standalone/tools/scfg_offline.py PRIVATE_FILE.swk1 --output PRIVATE_FILE.scfgbundle
python -m pytest -q firmware/standalone/tests
```

**Do not commit `.swk1` or `.scfgbundle` files**; they can carry personalized
voice-derived features. The CLI creates bundles with owner-only permissions on
POSIX and rejects overwriting existing files. Treat the source as private too.
The early GitHub Linux CI at commit `dc4ec5b` failed on a GCC array-bounds
warning in a test; this follow-up replaces the problematic test accessor and
must be judged against its own later CI run, not that earlier green Python run.

## 2026-11-19: isolated storage and compile-only board gate

Portable `core/persistent_store.hpp` adds fail-closed profile/ledger storage,
explicit first-time budget provisioning, re-read verification after each write,
and durable spend reservation across reboot. No existing NVS namespace is
read/cleared by the future `IsolatedNvs` adapter. A missing/corrupt budget on
normal boot is HOLD, never an implicit fresh ledger. `core/audio_guard.hpp`
adds a STOP-latched, exclusive mic/amp driver contract with mute-first init,
complete playback drain and no implicit recovery. Both are host-tested using
synthetic stores and audio hooks; they do not operate any real microphone.

`esp_app/` is a fresh ESP-IDF v6.1 standalone project that **compiles for
ESP32-S3 but intentionally starts in HOLD**. It checks read-only `sc_gpt` NVS
without erasing; the compiled ES7210/AW88298/I2S implementation is dormant.
It does not initialize camera/LCD/audio, Wi-Fi, USB handler, GPT or servos. Its default partition layout is not the
factory K151 layout. `esp_app/main/k151_contract.hpp` records official pin
constants; it does not attest to physical wiring, codec or panel compatibility.
The app deliberately contains no flash/install script or device API access.

The separate GitHub Actions workflow `.github/workflows/standalone-esp32s3.yml`
uses the pinned ESP-IDF v6.1 release tag (commit
`fff9895c82d744c7237be8847347bdd1b07c6643`) and publishes only an ELF
machine/slot-length/SHA manifest when a real build succeeds. A host `g++`
PASS does not imply this CI's ESP32 build PASS. Do not flash, merge or
replace the factory firmware based solely on compilation.

### 2026-11-19 follow-up hardening

The portable persistence contract now refuses outbound stages until a fresh,
durable three-request reservation exists. It exposes three **one-shot** stage
permits, strictly ordered `transcribe → respond → synthesize`. Duplicate,
out-of-order or post-STOP stages are rejected; reboot cannot restore in-RAM
permits. The caller MUST still gate each real HTTP request by the `Session`
epoch/timeout/state and must invalidate unused permits on STOP/error.

`AudioGuard` turns the amplifier off independently even if the mic-off driver
reports failure: stop/initialization/manual resume never short-circuit the
separate mute attempts. These are mock-hook tests, not actual K151 I2S proof.

The initial independent ESP-IDF v6.1/ESP32-S3 HOLD target compiled at
[GitHub Actions run 44434628479](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44434628479)
from commit `b1f98e168564`: Xtensa ELF (e_machine 94), app 197,024 bytes,
bounded by observed 5,177,344-byte OTA app slot. The app does NOT contain real
microphone, speaker, LCD, USB or GPT functionality and must NOT be flashed.

### 2026-11-19 codec driver compilation (no audio run)

`esp_app/main/k151_codec_port.{hpp,cpp}` links `esp_codec_dev==1.6.2`,
ES7210, AW88298, ESP-IDF I2S STD output / four-slot TDM input and the
documented K151 GPIO and I2C pins. `app_main` links only a marker, **never
constructs or invokes the codec**. `prepare()` requires explicit independent
owner, board and power/reset confirmations; there is no caller.
Codec I/O is limited to 10ms chunks. Reads/writes check actual codec return
codes and latch errors. A partially failed codec open attempts an independent
close rather than silently declaring the amplifier muted. Closure failures
remain faults, not evidence of electrical safety. `core/pcm_frame.hpp` host
tests channel-0 extraction and rejects malformed/interleaved frames.

[ESP32-S3 build of the codec driver](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44436984692)
passed for commit `1bdd94441957`, 197,152-byte app and Xtensa ELF.
Later commits must be judged against their own CI runs. Power rails/expander
reset, board LCD variant, real mic/reference lane mapping, USB enable and
physical STOP latency have NOT been established or enabled. No firmware binary
may be installed as a consequence of these builds.

## 2026-11-19 private wake WAV enrollment and offline evaluation

The host-only C++20 tools `tools/wake_wav_enroll.cpp` and `tools/wake_wav_eval.cpp` accept private 24kHz mono PCM16 WAVs, use the same MFCC/DTW core, and generate/evaluate SWK1 locally. Enrollment requires 1-3 templates, at least 5 distinct held-out positive inputs and 10 negative inputs; exact duplicate PCM across those groups is refused. Output is an exclusively created private profile, never an API request. See `docs/2026-11-19-wake-wav-enrollment.md`. No real Korean speech performance or physical K151 recording is claimed.

## 2026-11-20 private recording dataset preflight (offline only)

`tools/wake_corpus_template.py` creates an exclusive, unpopulated private
`*.wake-corpus.json` manifest; it never records audio. The paired
`tools/wake_corpus_audit.py` reads already recorded WAV files, screens exact
PCM duplication and malformed audio, and verifies that declared enrollment,
calibration, and independent evaluation sessions do not overlap. It reports
only aggregate counts, durations, and heuristic audio-quality warnings.
`CORPUS_STRUCTURALLY_SCREENED` does NOT certify labels, independence, real
Korean wake recognition or installation readiness. See
`docs/2026-11-20-private-wake-corpus-preflight.md`. Actual speech files and
private manifests must never be committed to GitHub.

`tools/wake_corpus_pipeline.py` adds an **offline, source-compiled** workflow:
strictly screen a local private corpus; feed enrollment and calibration
recordings only to the C++ MFCC/DTW SWK1 writer; then use independent
user-labeled evaluation recordings and publish the new private profile only
after both C++ stages return valid results. `--check-only` requires no C++
compiler. This workflow does not verify Korean wake accuracy or authorize
hardware installation. See `docs/2026-11-20-wake-corpus-offline-pipeline.md`.

## 2026-11-19 K151 power / LCD evidence (probe compiled, never invoked)

`core/board_evidence.hpp` and `esp_app/main/k151_readonly_probe.cpp`
add bounded observation-only I2C support for AXP2101/AW9523/FT6336 and
ES7210/AW88298 ACKs. No power register, amp reset or LCD initialization is
performed; a register-pointer read may still affect a device, which is why the
probe is not run in HOLD. The exact AW9523 reset sequence is a data-only
source reference and has no executor. FT6336 vendor/firmware fields can yield
an ILI9342E **candidate**; everything else remains unknown, including C.
No observation is a hardware authorization or an electrical mute proof.

See `docs/2026-11-19-k151-i2c-readonly-preflight.md` for pinned sources,
evidence limits, and required physical approval. Host parser and boot source
guards are tested; only a real ESP32-S3 CI build establishes cross-compilation.

## 2026-11-19 SCFG USB port compile-only stage

The independent `esp_app` now links `K151ScfgUsbPort`, a dedicated
ESP32-S3 USB Serial/JTAG SCFGv1 receiver. The boot HOLD app references only
its marker; it never calls `start`, so it does not install the USB driver
or open a port. The runtime API explicitly guards trusted local enrollment,
preserves a STOP latch, handles only feature data and returns fixed no-secret
SACK frames. The K151 factory firmware and actual USB console are unchanged.
Source and remaining limits: `docs/2026-11-19-k151-usb-compile-only.md`.
