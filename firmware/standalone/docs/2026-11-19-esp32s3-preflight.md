# Standalone K151 ESP32-S3 build-only preflight — 2026-11-19

Status: **COMPILED_NOT_APPROVED_FOR_DEVICE_INSTALLATION**.

## Actual GitHub verification

- Commit: `b1f98e16856438c790c3258ece39e87a3478308b`
- [GitHub Actions job / push run](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44434628479)
- Target: `esp32s3`, ELF `e_machine=94` (Xtensa)
- ESP-IDF v6.1 tag commit: `fff9895c82d744c7237be8847347bdd1b07c6643`
- ELF: 4,943,608 bytes, SHA-256 `581a5a390a7af3521b52d780fe77e36e5efec35fd06db08cd6ab616eae8d1717`
- APP: **197,024 bytes**, SHA-256 `a106a4b09ebf47c640e7967b65eb126525b9fe11a943e08d2206ccb401a6e691`
- K151 observed OTA APP slot from user's local report: **5,177,344 bytes**.
  The observed slot size is checked; it does **not** determine which slot can be
  replaced or prove compatibility with existing bootloader/partitions.
- CI uploaded only a build proof manifest, not the app binary.
- Hardware accessed: no. Firmware installed: no. Paid API requests: no.

## Scope of this particular binary

A minimal independent app that logs HOLD and reads only the new `sc_gpt` NVS
namespace, while never calling manufacturer `Hal::init`/factory reset,
servo motion, AI or network functions. `nvs_flash_init` error handling has no
automatic erase. The storage adapter's write gate is never armed. No
LCD/USB/microphone/ES7210/AW88298/I2S/API functionality is started or tested.
Generated partition table and bootloader are NOT replacements for the factory
image. Any future installation would require a separate explicit decision.

## Verification limitations and next steps

1. Existing SDK board pin declarations were read at
   [the pinned official source](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/config.h),
   but LCD ILI9342E/C detection, power rails and I2S/TDM codec sequence remain
   untested; static GPIO values are not evidence of successful audio capture.
2. The new portable `AudioGuard` and NVS `PersistentGuard` passed local host
   checks with mock drivers. Verify the later ESP-IDF adapters separately.
3. A real acoustic acceptance test must measure new Korean `조수야` utterances
   and false wakes, microphone resources, stop latency, Wi-Fi/TLS and audio
   replay; none is proven by this build.
4. Do not deploy a whole-flash image, run flash commands, modify OTA selection,
   erase NVS, move servos or run paid API calls on the existing robot.
