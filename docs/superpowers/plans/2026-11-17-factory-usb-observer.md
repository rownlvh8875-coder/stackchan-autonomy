# Factory USB observer implementation plan

> Execute inline in the existing isolated worktree; update the local progress ledger.

**Goal:** Prepare a read-only K151 USB camera/event observer and optional GPT vision tool.
**Architecture:** A portable C++ SCOB dispatcher plus ESP-IDF HAL adapter; a bounded
Python serial client with explicit identity pairing; existing GPT/MCP opt-in extension.
**Tech stack:** C++17, ESP-IDF v6.1 (fff9895c82d744c7237be8847347bdd1b07c6643), Python,
pyserial, Pillow, existing OpenAI Responses and MCP SDKs.
**Spec:** [approved design](../specs/2026-11-17-factory-usb-observer-design.md).
**Global constraints:** No device access, paid API call, flash, erase, provisioning or
actuator command. Build inputs must be pinned. Failed protocol/source checks are errors.
No media/identifiers in normal logs or text history. Installation remains HOLD even
if compilation succeeds; production authentication and backup/recovery remain unresolved.
**Review focus:** Bounds, boot/device/nonce binding, cleanup on cancellation and failed
writes, real firmware vs host test evidence, consent before capture/cloud quota.

## 1. PC protocol, pairing and diagnostics

- [x] RED: literal packets with independent CRC, fragmentation/noise/overflow/errors;
  socket byte-stream peer covers handshake, wrong identity/boot/nonce, snapshots and failure.
- [x] Add strict models/codec (`observer_protocol.py`), serial client/profile
  (`observer.py`) and metadata-only `stackchan-observe` CLI (`observer_cli.py`).
- [x] Enforce 32-byte header, metadata4096/JPEG131072 limits, boot16 and nonce16,
  1MiB boot noise, 1–30s deadlines, DTR/RTS inactive before open, no retry.
- [x] Validate JPEG SHA256, actual decode/dimensions/pixels/freshness; never save media.
- [x] Pin pyserial; test cancellation drains the one serial worker and closes the link.

## 2. Firmware prototype and real build attempt

- [x] RED: compile/run host tests against missing portable codec/dispatcher, then implement
  the same core in `firmware/observer/` with synthetic backend cleanup and opcode rejection.
- [x] Implement native USB Serial/JTAG worker; event cache maps official HeadPetGesture
  0–4 and ImuMotionEvent0–2. Unknown readings/pose remain null. Camera uses TryLockFrame,
  quiet single capture and bounded JPEG encoding; no actuator calls.
- [x] Provide deterministic patch/apply tooling for official SHA28b9f0c8… and pin resolved
  dependency commits. Reject incompatible USB-console configuration; opt-in defaults off.
- [x] Attempt actual ESP32-S3 build with pinned IDF, record input/output hashes and exact
  command. If blocked, record the concrete blocker; host tests never count as firmware build.

## 3. Optional GPT/MCP image observation

- [x] RED: actual Responses SDK with MockTransport, consent/stale source before quota,
  one image and sanitized sensor metadata, strict answer and no text-history retention.
- [x] Implement `GPTChat.observe` and optional `stackchan_gpt_observe(question)` only when
  `--gpt --observer-port` and image opt-in are present. Preserve existing default tools.
- [x] Test actual MCP session, fixed markers/errors, no media/port/device IDs in output.

## 4. Verification, documentation and integration

- [x] Add installed-wheel observer/SDK checks and portable core CI where toolchain exists.
- [x] Run targeted tests, full suite, Ruff, package verification and real build attempt.
- [x] Fresh whole-change review; one tested fix pass; ledger every finding/ruling.
- [x] Document preparation vs installation, operator HOLD prerequisites and pending real
  hardware/vision/coexistence checks; record validation and update roadmap/work log.
- [x] Commit and fast-forward existing `feat/transport-soak`, push normally; verify hosted
  Linux/Windows jobs. Do not merge main, publish environment or install firmware.
