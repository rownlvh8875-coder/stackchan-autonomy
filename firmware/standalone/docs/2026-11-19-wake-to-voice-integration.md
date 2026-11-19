# Wake-to-voice integration checkpoint (2026-11-19)

Status: **OFFLINE INTEGRATION ONLY — NO INSTALL / NO LIVE API**.

- `core/wake_voice_entry.hpp` connects a pre-enrolled 24kHz PCM wake feature to the existing session state machine and offline STT → Responses → TTS orchestration.
- It rejects silence, unknown signatures, STOP, missing owner consent, and wake events while speaker playback is active. A separate caller must confirm question start before passing bounded question PCM to the paid-call ledger.
- `tests/wake_voice_entry_test.cpp` uses synthetic sine-wave features and fake API/speaker ports, with zero sockets and no microphone/device. This **does not** validate recognition of the Korean phrase ‘조수야’ or identify a speaker.
- The ESP-IDF HOLD entrypoint only includes the new header for compile visibility; no startup activation or physical audio/network access occurs.

## Remaining work and hardware acceptance gates

1. Linux C++ host compilation/test must pass in CI. The Windows laptop currently lacks `g++`; its WSL virtual disk path is missing, so no automated repair was attempted.
2. ESP-IDF v6.1 ESP32-S3 compile-only CI must pass, with manifest/APP size. This proves linkage only, not correctness on K151.
3. A microphone capture/segmentation adapter, 24kHz PCM real input, VAD end-of-question, robust noise/false-wake trials, local enrollment UI, and echo cancellation/playback inhibition are still required.
4. For real hardware: confirm two independently restorable factory backups and OTA slot, GPIO/power/codec routing, STOP power policy, NVS retention and recovery, and explicit installation approval. Do not flash, erase, change OTA state, or move servos.
5. Network configuration, credentials and API billing require separate owner consent and real test authorization; default remains disabled.

Do not label an offline synthetic or compile-only PASS as a physical voice-recognition or successful hardware test.
