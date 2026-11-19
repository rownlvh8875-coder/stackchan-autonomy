# K151 I2C diagnostic and panel-hint preflight — development only

**NO FLASH / NO DEVICE INSTALL / NO PIN CONFIGURATION AT BOOT / NO ELECTRICAL MUTE PROOF.**

## Verified pinned-source findings

- `m5stack/StackChan@28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc` uses I2C1 on GPIO12/11; AXP2101 0x34, AW9523 0x58, FT6336 0x38. The AW9523 constructor writes configuration, and its `ResetAw88298` writes AW9523 register 0x02 value 0x03, delays 10ms, writes 0x07, delays 50ms. This also affects shared board control; **do not run the sequence from a diagnostic or startup path**.
- Same official file's `ReadControllerVersion()` writes `{0x00,0x00}` to set FT6336 work mode, then reads six bytes from 0xA3. Firmware ID 0x12 plus vendor 0x11 is used as an **ILI9342E hint**; other cases are treated as C by that code, but our preflight must call them **unknown** because that negative branch is not independent panel identification. Reading without the work-mode write might not return a usable result.
- `78/xiaozhi-esp32@49b4380b3faa0ceadd28a3e78aaf0f311c46c57e` contains the pinned CoreS3 24kHz TDM/STD audio driver; `espressif/esp_codec_dev==1.6.2` contains ES7210/AW88298 codec adapters. The presence of I2C ACKs alone cannot establish power rails, correct module identity, GPIO electrical safety, amplified output mute or LCD type.

## Current code

- `core/board_evidence.hpp` interprets I2C ACKs and six read-back bytes, preserving unknowns. It intentionally offers NO `authorize_audio` API. The AW9523 reset sequence is a **data-only reference plan**, with no executor and no hardware writes.
- `esp_app/main/k151_readonly_probe.{hpp,cpp}` provides an **explicitly gated** I2C1 probe that polls the STOP latch between bounded transactions. It performs I2C address probes and optionally transmits only the FT6336 register pointer `0xA3` before receiving six bytes. No work-mode configuration, PMIC power writes, expander reset writes, I2S, servos, camera, network, or API calls occur. This is not a promise that GPIO multiplexing will remain unchanged if the function is later called: constructing the master bus itself configures pins. A probe transaction may still affect a device in unexpected ways.
- `esp_app/main/app_main.cpp` logs the compiled marker **only** and never constructs or calls the probe. Boot remains the existing NVS read/hold loop. No hardware I2C attempt occurs in this CI image.

## Validation / safety boundaries

- Run host `pytest -q firmware/standalone/tests` and inspect GitHub Actions ESP-IDF v6.1 ESP32-S3 build. Host fixtures test valid/invalid panel hints, failed reads, I2C device ACK evidence, reset plan constants, and source-level enforcement of the HOLD entrypoint. CI compile/link cannot establish real peripheral behavior.
- Before any physical probing obtain separate owner approval; verify the exact K151 revision and state, factory flash backups, safe USB/bootloader rollback, and shared I2C ownership. The existing NVS init even without explicit erase can touch device state. Define physical STOP independent of synchronous I2C (30ms timeout does not prove instantaneous STOP).
- **No AXP2101 regulator changes or AW9523 reset/write are implemented.** A power sequence cannot be validated by reproducing manufacturer register constants alone. Real live audio stays HOLD, as do LCD initialization and GPT network calls.

## Source links

- [M5Stack board constructor, PMIC and expander control](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc)
- [Pinned K151 pin assignments](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/config.h)
- [Pinned ESP-IDF I2C master API](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2c/include/driver/i2c_master.h)
