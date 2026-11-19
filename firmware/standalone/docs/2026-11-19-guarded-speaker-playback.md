# Guarded K151 speaker playback — compile-only checkpoint (2026-11-19)

Status: **HOST/SYNTHETIC VALIDATION ONLY; NOT APPROVED FOR DEVICE INSTALLATION.**

## New components

- `core/guarded_voice_speaker.hpp`: wraps the existing STT → GPT → TTS `VoiceSpeakerPort` with `AudioGuard` power ownership. It rejects empty/oversize PCM, missing owner consent, STOP, active microphone capture, and concurrent playback. It claims an atomic speaker-busy latch, checks consent/STOP again after taking ownership, and requires microphone-off + low-volume amplifier-on before invoking the PCM sink.
- Playback success requires the sink to acknowledge completion, the same monotonic-clock origin, AudioGuard DMA-drain hook to succeed, and the amplifier-off hook to succeed. Only after those operations does the busy latch clear.
- Any output failure, late STOP, consent withdrawal, timestamp regression or drain/mute uncertainty triggers `AudioGuard::stop()`. The speaker's fault and busy latches remain set; there is no automatic retry, implicit reconfiguration, or ownerless resume.
- `esp_app/main/k151_pcm_speaker_sink.hpp`: dormant K151 codec sink, slicing 24kHz mono PCM16 into at most 240-sample (10ms nominal) writes and checking STOP/consent between writes. It does not open codecs, change pin mappings or assert that the physical I2S path works. It assumes its `started_ms` has the same `esp_timer_get_time()/1000` time base. The synchronous codec write may take longer than 10ms and has no proven real-time cancellation bound.
- `core/audio_guard.hpp`: a later STOP no longer converts an already-faulted audio driver into a manually resumable STOP state.
- The default ESP32-S3 HOLD `app_main()` merely includes the dormant sink and wrapper for compilation. It does not construct, initialize, play, record, or connect the K151 codec.

## Tests and acceptance boundary

- Existing fake voice-turn pipeline now uses `GuardedVoiceSpeaker`, proving microphone-off before amplifier-on, PCM playback, drain-then-mute and the final cooldown in the **fully offline** host test.
- Negative host cases exercise PCM sink error, STOP during playback, drain failure, invalid timestamp, microphone capture overlap, output already busy, and repeated playback after fault. Test hardware/API are fake; no real waveforms or secret keys are involved.
- This stage does **not** verify actual speaker gain, I2S/TDM routing, amplifier power/reset, DMA empty status, PSRAM, Korean wake-word accuracy, electrical safe STOP, acoustic feedback/echo or actual audio timing.
- Before deployment a physical board audit, measured hardware mute/drain semantics, confirmed factory-backup restoration and compatible OTA slot, approved firmware installation, and real acoustic/integration testing are required. No flash, OTA, NVS write, paid API call or actual actuator/microphone/speaker access occurred.
