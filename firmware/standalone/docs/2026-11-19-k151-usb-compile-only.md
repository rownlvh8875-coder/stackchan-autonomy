# ESP32-S3 native USB SCFG transport — compile-only prototype

**No physical USB connection, no app activation, no NVS write, no Wi-Fi/API, no firmware installation.**

## Source and constraints

- Pinned ESP-IDF v6.1 `components/esp_driver_usb_serial_jtag/include/driver/usb_serial_jtag.h` exposes `usb_serial_jtag_driver_install`, bounded read/write APIs, and uninstall. Installation and removal must occur on the same CPU core.
- The user's original K151 ROM was identified as Espressif USB Serial/JTAG, but the source pin path and stock firmware USB console conflicts must be verified separately before any firmware installation.
- The existing portable `ScfgStreamReader` accepts framed SCFGv1 with nonce/CRC and at most 8,192-byte payload; `EnrollmentServer` only accepts capped SWK1 voice features and keeps `configure` / `cloud_enable` unsupported. CRC is integrity, not identity authentication. USB physical access is the trust boundary.

## New dormant adapter

- `esp_app/main/k151_usb_scfg.{hpp,cpp}` compiles a dedicated native USB Serial/JTAG receiver. It is never constructed or invoked from the HOLD `app_main`. Only a link marker is referenced.
- `start()` requires three explicit trusted-local inputs (owner mode, separate UART console, trusted profile store) and a clear physical STOP latch; no packet or remote service can set these conditions in the current image. If a USB driver is already installed, it refuses takeover. It also refuses to start if the ESP-IDF USB Serial/JTAG console option is enabled. `sdkconfig.defaults` selects UART as default console and disables the secondary console.
- `poll_once()` processes at most 96 bytes per call, checks a caller-provided atomic STOP latch between bytes, rejects malformed SCFG with the portable parser and sends only fixed 18-byte SACK replies. Sensitive incoming frame payloads and temporary input buffers are zeroed after processing. No raw PCM opcode, waveform log or credentials are supported. A partial TX enqueue is a fault, not a success; successful enqueue is **not** a proof the host received the ACK.
- Local STOP aborts enrollment and prevents it from resuming, but status and stop protocol requests may still receive a fixed ACK. There is **no** hardware interrupt-based electrical stop; bounded API calls do not prove hard realtime response.
- `shutdown()` must be called on the same core where the driver was installed. It does not release manufacturer AI or change a servo.

## Missing before device integration

- A physically authenticated local mode/menu or button for enrollment; no generic USB opcode may arm it.
- An approved isolated NVS profile-store callback, write verification and rollback plan; NO store callback is supplied by `app_main`.
- USB console and flashing-port ownership tests, COM port recovery, disconnect/reconnect and timeout tests on the real K151.
- High-priority STOP scheduling, asynchronous USB service for responsiveness and bounded TX drain.
- Audio acquisition and 24kHz MFCC generation on device; this adapter does not record speech or call GPT.

The work is **compile/test-only**. Do not flash or merge to main based on host tests/CI.

Source: https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_usb_serial_jtag/include/driver/usb_serial_jtag.h
