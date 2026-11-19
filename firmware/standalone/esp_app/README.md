# K151 compile-only ESP-IDF v6.1 standalone preflight

**NO DEVICE FLASH, OTA, NVS MUTATION, SERVO OPERATION, OR INSTALLATION APPROVAL.**

This is an independent firmware project, not a patch to manufacturer `Hal::init()`.
The original `main`, `feat/transport-soak`, and factory firmware are unchanged.

The image boots to a persistent HOLD loop. It **never** initializes the
manufacturer AI, servo/UART, codec, amplifier, LCD, camera, microphone, USB
settings receiver, Wi-Fi or any paid API client. It only attempts to initialize
NVS without invoking erase and checks the new `sc_gpt` namespace READONLY.
Absent/corrupt budget is an error, not an automatic reset. Cloud stays disabled.
There is no physical installation or even a compatible partition table here.

`main/k151_contract.hpp` records verified K151 source constants (24kHz,
GPIO 0/33/34/14/13 for I2S, GPIO 12/11 for I2C, 320x240 LCD) from
[m5stack/StackChan@28b9f0c](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/config.h).
The actual panel variant (ILI9342C/E), ES7210/AW88298 sequencing, dual
reference/voice input TDM arrangement, GPIO0 boot-button conflict, LCD/USB
routing and power-up are NOT verified on the target; no I2S calls are made.

The NVS adapter is `main/nvs_port.cpp`. It uses `nvs_flash_init()` with **no**
automatic `nvs_flash_erase`, the isolated `sc_gpt` namespace, and allows
`wake_profile`/`budget` keys only. The WRITE method requires explicit local
approval, not a USB opcode; the current `app_main` never grants it. The portable
`PersistentGuard` additionally verifies a post-commit read-back and latches
any storage uncertainty. NVS initialization is not guaranteed to keep every
physical NVS byte unchanged; this project is not to be run without approval.

Build in an isolated ESP-IDF v6.1 environment (exact tagged SHA
`fff9895c82d744c7237be8847347bdd1b07c6643`):

```sh
idf.py -C firmware/standalone/esp_app set-target esp32s3
idf.py -C firmware/standalone/esp_app build
```

These compile commands do not access a robot. **Do not run flashing commands
printed by ESP-IDF.** The generated bootloader, partition table and OTA data
are NOT compatible installation inputs for the backed-up factory layout.
This project has no upload or flash workflow. The separate build CI records
ELF/APP SHA256 and enforces the observed 5,177,344-byte K151 app-slot bound,
without publishing a firmware binary.

Before real hardware wiring: inspect factory LCD variant and power/I2S TDM
codec driver, enforce mute-first and stop-latched `AudioGuard`, implement
an isolated USB SCFG handler with physical owner permission, and measure actual
memory/latency/Korean wake recognition. No manufacturer AI or servo init.
