# K151 physical head-touch local-presence gate (2026-11-19)

**RECONSTRUCTION / DRAFT — DO NOT FLASH OR OPERATE REAL HARDWARE.**

Pinned M5Stack StackChan source `m5stack/StackChan@28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400`:
- `firmware/main/hal/hal_head_touch.cpp` polls the 3-channel head-touch result each 50 ms and emits `HeadPetGesture` actions.
- `firmware/main/hal/drivers/Si12T/Si12T.h`: Si12T 7-bit I2C address `0x68`, OUTPUT1 register `0x10`, three 2-bit intensity readings.
- `firmware/main/hal/drivers/Si12T/Si12T.cpp`: reads OUTPUT1 through `i2c_master_transmit_receive`; factory `si12t_setup` **writes** sensitivity, CTRL and calibration registers, and must NOT be invoked before approved hardware integration.
- `firmware/main/hal/board/config.h`: GPIO0 is both boot input and I2S MCLK, so an independent GPIO0 button path is not assumed.

New `core/head_touch_consent.hpp` implements a **physical-presence**, not biometric identity, policy: start only on an independently owned sensor, require clean release; a 3-second touch hold and 300ms clean release open a bounded 2-minute owner-presence window. AFTER the trusted local UI states that credential entry was reviewed, a *separate* clean release + 3-second hold + clean release grants one final 15-second consent ticket. STOP, I2C read failure, invalid intensity, missed 250ms sample deadline, clock rollback or expired window fail closed. A short tap, stuck-on-boot touch, repeated ticket use or remote SCFG messages must never grant consent. The state machine itself contains **no secret data**.

New `esp_app/main/k151_head_touch_owner.{hpp,cpp}` is compiled into a standalone ESP-IDF v6.1 image; `app_main` **links only a static marker**. It DOES NOT start I2C, install the touch device, initialize Si12T, calibrate, write registers, access Wi-Fi or change the robot. A future approved local owner task must independently own and initialize the board's shared I2C bus, verify board identity and prove the Si12T was configured safely before the read-only adapter can attach. The adapter *only* sends an OUTPUT1 register pointer and receives one byte. The local physical-owner latch is withdrawn on STOP, bad reads, or sampling errors. 
The adapter offers `begin_owner_setup()` only while fresh touch-presence evidence
is available and the local UI claims a separate trusted input mode.
`request_final_confirmation()` checks `OwnerSetupPhase::confirm` before opening
any second-touch stage, and `finish_owner_setup()` consumes the one-time physical
token before asking the existing owner controller to commit RAM credentials. There is no network/USB code path that activates the adapter.

The portable host fixture additionally composes a touch-presence event with the existing `OwnerSetupController`: physical contact alone cannot set `trusted_local_input`. That independent signal must originate from a future *verified* on-device input path. The final one-use gesture proof can authorize `OwnerSetupController::confirm()` only after fake credentials are staged. No real credentials are committed or transmitted.

**NOT PROVED:** hardware gesture detection and false-positive rate, electrical contact, identity authentication, reliable I2C sampling under load, physical STOP interrupt latency, LCD UI, safe first-use secret entry, Wi-Fi association or real GPT/STT/TTS. The official factory head-touch initialization cannot run in the standalone HOLD image without touching registers; it remains intentionally unimplemented.

## Final confirmation API restriction

The device-facing `K151LocalOwnerSetup::confirm()` is **private** and can be
invoked by `K151HeadTouchOwner` as a friend. This prevents accidental
production-device call sites from passing `true` without spending a validated
second physical touch ticket. The portable `OwnerSetupController` remains
public for host-only tests but is encapsulated by the device adapter. This is
a source-level authorization boundary, not a proof of authenticated identity.
