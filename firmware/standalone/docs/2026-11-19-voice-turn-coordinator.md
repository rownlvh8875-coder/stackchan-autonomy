# Wake → guarded microphone → STT/GPT/TTS coordination (2026-11-19)

Status: **HOST/COMPILE-ONLY PROTOTYPE; NO DEVICE INSTALL OR LIVE NETWORK.**

## What was connected

- `VoiceTurnCoordinator` consumes a **previously validated wake epoch** and an `AudioGuard` that the owner would have to initialize separately after confirming exact board identity and physical STOP.
- `arm()` checks the session epoch, owner consent, STOP and speaker state before entering microphone capture. It does not initialize hardware or turn on the mic by itself unless an already-authorized guard is supplied.
- `poll()` consumes one 20 ms question frame through the 10 ms K151-compatible `MicFrameBridge`, acknowledges speech start **once**, and waits for bounded silence completion.
- Before any STT/Responses/TTS dispatch, `AudioGuard::capture_end()` must succeed. `WakeVoiceEntry::answer_captured()` enforces matching epoch and one-shot question consumption with durable paid-request reservation.
- Any capture I/O error, STOP, consent withdrawal, state/epoch mismatch, elapsed ready timeout, or microphone-off failure latches a fault, resets captured PCM, invokes guarded STOP/mute and cancels unspent stage permits. There is **no automatic restart**.
- `app_main()` includes the new header solely for compile coverage. The perpetual HOLD behavior is unchanged: it never starts microphone, I2S, Wi-Fi, USB, codec or a real API call.

## Test scope and remaining obstacles

`tests/voice_turn_coordinator_test.cpp` uses fake audio hooks, fake 10 ms microphone PCM, fake API replies, and a fake speaker. It checks the complete local path and failure cases without external connectivity. This **does not** prove that the Korean phrase '조수야' is recognized or that a K151 physically captures/plays sound.

The following must still be independently validated before any installation: real 24 kHz sample timing and TDM channel routing, device power/codec reset sequence, physical STOP latency, speaker and microphone mutual exclusion during actual playback, PSRAM/heap headroom for up to 8 seconds of PCM (~384,000 bytes before overhead), false-wake and noisy-room recordings, actual network TLS and budget credentials, two independently restorable factory backups and OTA/partition compatibility. **No flashing, NVS erase, API billing or hardware changes are approved by this artifact.**

The controller assumes serialized calls to `arm()/poll()/cancel()` and an externally maintained atomic STOP latch; no real-time concurrency or cancellation timing guarantee is made.
