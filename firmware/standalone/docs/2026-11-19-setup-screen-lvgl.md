# K151 first-use setup: privacy-only LCD view model and dormant LVGL adapter

**2026-11-19 / Draft PR #2 / NOT APPROVED FOR DEVICE INSTALLATION.**

## Verified sources

- M5Stack StackChan [pinned board implementation](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc) creates a SPI LCD, resets through AW9523, and selects its ILI9342C/E path after an FT6336 read. Neither the panel variant nor the electrical reset path is independently verified on this user's physical K151.
- M5Stack [display adapter](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan_display.cc) uses LVGL and RGB565, 320x240.
- LVGL v9.5.0 [tag](https://github.com/lvgl/lvgl/releases/tag/v9.5.0) is the version declared by this standalone component.

## Implemented (offline/compile-only)

1. `core/setup_screen_model.hpp` maps the existing `HeadTouchConsent` and `OwnerSetupController` states to fixed ASCII strings for a 320x240 display. It never receives SSID, passphrase or token bytes and never interpolates a secret, raw USB payload or arbitrary cloud-controlled text. STOP/fault override all other views. Inconsistent owner and touch state fails closed to an error view.
2. `esp_app/main/k151_setup_lvgl.{hpp,cpp}` accepts an **already initialized and independently verified** LVGL display and an explicit external LVGL lock. It creates only three text labels and consumes only the fixed view model. The adapter does **not** initialize a panel, reset the AW9523, start touch/USB/Wi-Fi, mount NVS, run a GPT request or control servos.
3. The HOLD `app_main.cpp` references the adapter's static `compiled_link_marker()` only. No `K151SetupLvgl` object is created on boot. `K151SetupLvgl` has no raw credential-input methods.
4. Offline host tests enumerate touch/owner states, verify STOP/error precedence, text length/ASCII bounds, phase mismatch handling and absence of fabricated credentials. A static test blocks implicit LCD startup in HOLD.

## Explicitly NOT done

- An authenticated and confidential PC credential transport has **not** been implemented. The display says that a trusted PC input is *required*, not that it exists. Do not send OpenAI keys or Wi-Fi passwords over unencrypted SCFG USB, and do not treat a touch gesture as identity authentication.
- The LCD does not display SSID, API token suffix, fingerprint or credential length; this conservative privacy display is **not sufficient to prove that the PC submitted the intended credentials**. A secure device-authenticated pairing channel and a user-reviewable binding are still required.
- Physical panel identification, RGB565 rendering, LVGL lock ownership, PSRAM/heap fragmentation, label visibility, touchscreen input, live Si12T sampling and real STOP latency require a separately approved physical test with a verified recovery image.
- No firmware binary is distributed. No `main` merge, flash/OTA, manufacturer NVS modifications, secrets persistence or fee-bearing API calls.

The ESP32-S3 GitHub Actions job compiles the optional view adapter but does not execute it. Successful compilation does **not** establish hardware display compatibility.
