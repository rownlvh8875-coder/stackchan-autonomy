# K151 Standalone GPT: portable safety core (reconstruction)

**STATUS: HOST-TESTED ONLY. NOT APPROVED FOR DEVICE INSTALLATION.**

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

- `조수야` Korean keyword DSP/MFCC-DTW and real acoustic thresholds; NVS adapter,
  USB transport, board pin/power/LCD/codec drivers, I2S capture/playback,
  Wi-Fi/TLS/clock/HTTP + STT/Responses/TTS clients, speaker feedback suppression,
  exact IDF link/build, ROM recovery/OTA slot handling.
- Real hardware timing, power, RAM/PSRAM, Korean wake accuracy, API charges, or
  firmware behavior on K151. A green host test is **not** an ESP32-S3 build.

No automatic flashing, no manufacturer AI startup, no servo initialization,
no factory settings erase, no model fallback, and no cloud request are provided.
USB enrollment must transmit features only; this module rejects large chunks
but the eventual device handler must validate the feature schema before NVS.
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
