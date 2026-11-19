# K151 hardware and Korean wake acceptance matrix — future bench protocol

Status: **DESIGN / EVIDENCE REQUIRED / NOT DEVICE INSTALLATION APPROVAL**.

## A. Offline prerequisites — no robot access

| Gate | Required evidence | Current determination |
|---|---|---|
| Factory recovery | Two separate full-flash images independently verified, off-device copy, an independently demonstrated restore path | Not established in this work |
| Partition/OTA | Actual active boot slot, factory bootloader partition compatibility and safe rollback path | Unknown; user-reported two OTA slots do not identify active slot |
| Firmware integrity | Reproducible ESP-IDF v6.1 build manifest, ELF Xtensa, APP size within observed 5,177,344-byte slot | Compile-only build evidence exists; not install compatibility |
| Secret isolation | Credentials absent from Git, stdout, firmware images and test artifacts | Must verify before any live API request |
| Installation decision | Separate explicit owner approval for a specific reviewed binary and recovery method | Not authorized |

Existing read-only tools: `tools/offline_factory_recovery.py` and `tools/readiness_snapshot.py`. Neither identifies an active slot, flashes, or proves restoration. For previously captured, synchronized instrument timing records, `tools/bench_trace_audit.py` checks only event order and timing arithmetic; [the bench log protocol](2026-11-19-bench-trace-audit.md) explains why its outputs can never certify physical safety or installation.

## B. Separate physical authorization required — no automatic I2C/USB probing

| Gate | Bench observation and abort condition |
|---|---|
| Exact board | Confirm physical board revision and pinout before mapping or initializing I2C/I2S; no assumptions from a compatible reference board |
| Shared power/I2C | Record AXP2101 actual rail readings and ownership of shared I2C devices. Any mismatch is STOP |
| Amp reset | Independently verify AW9523/AW88298 reset and read-back without changing LCD/PMIC controls unexpectedly |
| Electrical mute | Measure amp output/enable state and power-down behavior; a successful codec API close is not evidence of physical mute |
| TX drain | Obtain real TX DMA-empty and codec-idle witnesses. `esp_codec_dev_write` return and elapsed time alone are not proof |
| Physical STOP | Measure actual wake-to-mute / write-block interruption latency under each fault, including a blocked write; missing bound is STOP |
| Audio routing | Measure true 24 kHz input/output, 16-bit mono PCM, TDM microphone/reference ordering, capture flush and playback completion |
| Memory | Prove location of allocations (internal RAM vs PSRAM) and live concurrent recording + TTS headroom, fragmentation and OOM handling |

Reference only: [M5Stack pinned board construction](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc) and [pinned K151 codec contract](../docs/2026-11-19-k151-codec-audit.md). These do not replace device-specific electrical measurements.

## C. Korean wake-word and speech validation (after bench approval)

The enrollment implementation uses 24 kHz PCM → MFCC/template-DTW features. `calibrate_wake()` requires at least **5 separate held-out positive** samples and **10 separate negative** samples for calibration, distinct from enrollment templates. That is a minimum **software input requirement**, not an adequate statistical accuracy study.

Capture additional independent real recordings across distance, noise, competing speech, different pronunciations and speaker self-playback. Keep training and evaluation disjoint, report raw true/false activations, denominator, test conditions and time/CPU measurements. No fabricated recognition percentage or biometric identity claim is permitted. The new [private host-only WAV evaluator](2026-11-19-wake-wav-offline-evaluation.md) checks bounded PCM input and compares user-labeled WAVs to an existing SWK1 profile without writing audio, enabling an initial *unverified* aggregate evaluation before hardware activation.

After verified speech capture, test the bounded question recorder, one-shot STT/Responses/TTS paid ledger, user consent withdrawal, API failure and STOP suppression. A mock or synthetic-waveform PASS cannot be presented as Korean recognition validation.

## D. Release decision

The existing `app_main` is a perpetual HOLD loop. `kK151PhysicalOutputEnabledInHoldImage=false`, `kK151SafeDmaDrainDriverAvailable=false` and `kAudioMemoryReadinessCanAuthorizeInstall=false`; the source is intentionally **not a usable voice robot image**. Do not change these flags to bypass missing measurements.

This matrix supplies evidence questions only. It does not authorize physical probing, API billing, firmware flashing, OTA selection, NVS mutation, servo movement or deletion of factory firmware. The user must explicitly authorize a separate, reviewed bench/installation procedure after independent recovery checks.
